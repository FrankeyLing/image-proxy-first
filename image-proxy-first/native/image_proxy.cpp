// image-proxy-first v2. C++17, self-contained codecs, no image data on stdout.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#include <shellapi.h>
#include <fcntl.h>
#include <io.h>
#include <sys/stat.h>
#else
#include <fcntl.h>
#include <unistd.h>
#endif
#define STBI_NO_HDR
#define STBI_NO_LINEAR
#define STB_IMAGE_IMPLEMENTATION
#include "vendor/stb_image.h"
#define STB_IMAGE_RESIZE_IMPLEMENTATION
#include "vendor/stb_image_resize2.h"
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "vendor/stb_image_write.h"

namespace fs = std::filesystem;
using Bytes = std::vector<unsigned char>;
using Clock = std::chrono::steady_clock;
struct Failure : std::runtime_error { int code; Failure(std::string m, int c=2):std::runtime_error(m),code(c){} };
void need(bool yes,const std::string& reason){if(!yes)throw Failure(reason);}
std::string utf8(const fs::path& p){return p.u8string();}
std::string quoted(const std::string& s){
    std::string o="\"";
    for(unsigned char c:s){switch(c){case '"':o+="\\\"";break;case '\\':o+="\\\\";break;
        case '\n':o+="\\n";break;case '\r':o+="\\r";break;case '\t':o+="\\t";break;
        default:if(c<32){char b[7];std::snprintf(b,7,"\\u%04x",c);o+=b;}else o+=char(c);}}
    return o+'"';
}
uint64_t number(const std::string& s){
    need(!s.empty()&&std::all_of(s.begin(),s.end(),[](char c){return c>='0'&&c<='9';}),"expected_nonnegative_integer");
    try{return std::stoull(s);}catch(...){throw Failure("integer_out_of_range");}
}
int integer(const std::string& s){auto n=number(s);need(n<=INT32_MAX,"integer_out_of_range");return int(n);}
struct Options{
    std::vector<fs::path> input;fs::path out;std::string preset="balanced",layout="smart",mode="auto",entry;
    int edge=1600,cap=240000,width=0,height=0,offset=0,stride=0,frame=0;
    uint64_t pixels=160000000,input_bytes=1073741824;bool trailing=false,custom_cap=false,custom_edge=false;
    bool has_crop=false;int crop[4]={0,0,0,0};std::vector<std::string> fallback_args;
};
Options parse(const std::vector<std::string>& a){
    Options o;o.entry=a[0];
    for(size_t i=1;i<a.size();++i){auto x=a[i];auto arg=[&](){need(i+1<a.size(),"missing_option_value:"+x);return a[++i];};
        if(x=="--out-dir")o.out=fs::u8path(arg());
        else if(x=="--preset")o.preset=arg();else if(x=="--layout")o.layout=arg();else if(x=="--mode")o.mode=arg();
        else if(x=="--max-bytes"){o.cap=integer(arg());o.custom_cap=true;}
        else if(x=="--max-edge"){o.edge=integer(arg());o.custom_edge=true;}
        else if(x=="--max-input-pixels")o.pixels=number(arg());
        else if(x=="--max-input-bytes")o.input_bytes=number(arg());
        else if(x=="--width")o.width=integer(arg());else if(x=="--height")o.height=integer(arg());
        else if(x=="--offset")o.offset=integer(arg());else if(x=="--stride")o.stride=integer(arg());
        else if(x=="--frame")o.frame=integer(arg());
        else if(x=="--time"){o.fallback_args.push_back(x);o.fallback_args.push_back(arg());}
        else if(x=="--black"||x=="--white"){o.fallback_args.push_back(x);o.fallback_args.push_back(arg());}
        else if(x=="--allow-trailing")o.trailing=true;
        else if(x=="--crop"){o.has_crop=true;for(int& v:o.crop)v=integer(arg());}
        else if(x.rfind("--",0)==0)throw Failure("unknown_option:"+x);
        else o.input.push_back(fs::u8path(x));
    }
    need(!o.input.empty()&&o.input.size()<=16,"one_to_sixteen_inputs_required");
    need(o.preset=="balanced"||o.preset=="fast"||o.preset=="text"||o.preset=="detail","invalid_preset");
    if(!o.custom_cap)o.cap=o.preset=="fast"?96000:o.preset=="detail"?300000:240000;
    if(!o.custom_edge)o.edge=o.preset=="fast"?1280:o.preset=="detail"?2048:1600;
    need(o.cap>=16000&&o.cap<=500000&&o.edge>=64&&o.edge<=2048,"invalid_proxy_limits");
    need(o.pixels>0&&o.input_bytes>0&&o.pixels<=1000000000,"invalid_input_limits");
    need(o.layout=="smart"||o.layout=="overview"||o.layout=="halves"||o.layout=="grid"||o.layout=="strips"||o.layout=="all","invalid_layout");
    return o;
}
Bytes read_file(const fs::path& p,uint64_t cap){
    auto n=fs::file_size(p);need(n>0&&n<=cap&&n<=INT32_MAX,"input_byte_limit");
    std::ifstream in(p,std::ios::binary);need(bool(in),"source_open_failed");Bytes b((size_t)n);
    in.read((char*)b.data(),std::streamsize(n));need(in.gcount()==std::streamsize(n),"source_short_read");return b;
}
int tiff_orientation(const unsigned char* d,size_t n){
    if(n<8)return 1;bool le=d[0]=='I'&&d[1]=='I';if(!le&&!(d[0]=='M'&&d[1]=='M'))return 1;
    auto u16=[&](size_t p)->uint32_t{if(p+2>n)return 0;return le?uint32_t(d[p])|(uint32_t(d[p+1])<<8):(uint32_t(d[p])<<8)|d[p+1];};
    auto u32=[&](size_t p)->uint32_t{if(p+4>n)return 0;return le?u16(p)|(u16(p+2)<<16):(u16(p)<<16)|u16(p+2);};
    if(u16(2)!=42)return 1;size_t off=u32(4);if(off+2>n)return 1;auto count=u16(off);
    for(size_t k=0;k<count;k++){size_t p=off+2+k*12;if(p+12>n)break;if(u16(p)==274&&u16(p+2)==3&&u32(p+4)==1){auto v=u16(p+8);return v>=1&&v<=8?int(v):1;}}
    return 1;
}
int orientation(const Bytes& b){
    if(b.size()>4&&b[0]==0xff&&b[1]==0xd8){size_t p=2;
        while(p+4<=b.size()){if(b[p++]!=255)break;while(p<b.size()&&b[p]==255)++p;if(p>=b.size())break;
            int mark=b[p++];if(mark==0xda||mark==0xd9)break;if(mark>=0xd0&&mark<=0xd7)continue;
            if(p+2>b.size())break;size_t n=(size_t(b[p])<<8)|b[p+1];if(n<2||n>b.size()-p)break;
            if(mark==0xe1&&n>=8&&std::memcmp(b.data()+p+2,"Exif\0\0",6)==0)return tiff_orientation(b.data()+p+8,n-8);p+=n;}
    }
    if(b.size()>8&&std::memcmp(b.data(),"\x89PNG\r\n\x1a\n",8)==0){size_t p=8;
        while(p+12<=b.size()){size_t n=(size_t(b[p])<<24)|(size_t(b[p+1])<<16)|(size_t(b[p+2])<<8)|b[p+3];
            if(n>b.size()-p-12)break;if(std::memcmp(b.data()+p+4,"eXIf",4)==0)return tiff_orientation(b.data()+p+8,n);p+=n+12;}}
    return 1;
}
struct Raster{int w=0,h=0;Bytes rgb;};
Raster orient(Raster&& s,int n){
    if(n==1)return std::move(s);Raster d;d.w=n>=5?s.h:s.w;d.h=n>=5?s.w:s.h;d.rgb.resize(size_t(d.w)*d.h*3);
    for(int y=0;y<d.h;y++)for(int x=0;x<d.w;x++){int sx=x,sy=y;switch(n){
        case 2:sx=s.w-1-x;break;case 3:sx=s.w-1-x;sy=s.h-1-y;break;case 4:sy=s.h-1-y;break;
        case 5:sx=y;sy=x;break;case 6:sx=y;sy=s.h-1-x;break;case 7:sx=s.w-1-y;sy=s.h-1-x;break;case 8:sx=s.w-1-y;sy=x;break;}
        std::memcpy(&d.rgb[(size_t(y)*d.w+x)*3],&s.rgb[(size_t(sy)*s.w+sx)*3],3);}
    return d;
}
Raster decode(const Bytes& b,const Options& o,int& rotation,std::string& mapping){
    Raster r;
    if(o.mode.rfind("raw-",0)==0){
        bool sixteen=o.mode=="raw-gray16le"||o.mode=="raw-gray16be";
        bool gray=o.mode=="raw-gray8"||sixteen;
        int components=gray?(sixteen?2:1):o.mode=="raw-rgba32"?4:3;
        need(gray||o.mode=="raw-rgb24"||o.mode=="raw-bgr24"||o.mode=="raw-rgba32","unsupported_raw_layout");
        need(o.width>0&&o.height>0&&uint64_t(o.width)*o.height<=o.pixels,"explicit_raw_geometry_required");
        uint64_t row=uint64_t(o.width)*components,stride=o.stride?o.stride:row;
        need(stride>=row&&stride*o.height<=b.size()&&uint64_t(o.offset)<=b.size()-stride*o.height,"raw_geometry_short_input");
        uint64_t total=uint64_t(o.offset)+stride*o.height;need(o.trailing||total==b.size(),"raw_trailing_bytes_rejected");
        r.w=o.width;r.h=o.height;r.rgb.resize(size_t(r.w)*r.h*3);int lo=65535,hi=0;
        auto value=[&](const unsigned char* p){return o.mode=="raw-gray16be"?(int(p[0])<<8)|p[1]:int(p[0])|(int(p[1])<<8);};
        if(sixteen){for(int y=0;y<r.h;y++)for(int x=0;x<r.w;x++){int v=value(b.data()+o.offset+y*stride+x*2);lo=std::min(lo,v);hi=std::max(hi,v);}
            mapping="linear_16bit_display_min="+std::to_string(lo)+"_max="+std::to_string(hi)+"_not_measurement_preserving";}
        for(int y=0;y<r.h;y++)for(int x=0;x<r.w;x++){auto p=b.data()+o.offset+y*stride+x*components;auto q=&r.rgb[(size_t(y)*r.w+x)*3];
            if(gray){int v=sixteen?(hi==lo?0:(value(p)-lo)*255/(hi-lo)):p[0];q[0]=q[1]=q[2]=(unsigned char)v;}
            else {int alpha=components==4?p[3]:255;for(int c=0;c<3;c++){int v=p[o.mode=="raw-bgr24"?2-c:c];q[c]=(unsigned char)((v*alpha+255*(255-alpha)+127)/255);}}}
        return r;
    }
    need(o.mode=="auto"||o.mode=="image","native_mode_requires_fallback");
    int channels=0;int w=0,h=0;
    if(!stbi_info_from_memory(b.data(),int(b.size()),&w,&h,&channels))throw Failure("codec_not_supported_or_invalid_input",78);
    need(w>0&&h>0&&uint64_t(w)*h<=o.pixels,"input_pixel_limit");
    if(stbi_is_16_bit_from_memory(b.data(),int(b.size())))throw Failure("high_bit_depth_image_uses_display_mapping_fallback",78);
    int desired=(channels==2||channels==4)?4:3;
    auto decoded=stbi_load_from_memory(b.data(),int(b.size()),&r.w,&r.h,&channels,desired);
    need(decoded!=nullptr,"native_decode_failed");
    try {r.rgb.resize(size_t(r.w)*r.h*3);
        if(desired==3)std::memcpy(r.rgb.data(),decoded,r.rgb.size());
        else for(size_t i=0;i<size_t(r.w)*r.h;i++)for(int c=0;c<3;c++){int a=decoded[4*i+3];r.rgb[3*i+c]=(unsigned char)((decoded[4*i+c]*a+255*(255-a)+127)/255);}
    } catch(...){stbi_image_free(decoded);throw;}
    stbi_image_free(decoded);rotation=orientation(b);return orient(std::move(r),rotation);
}
struct Region{std::string name;int x,y,w,h;};
std::vector<Region> regions(int w,int h,const Options& o){
    std::vector<Region> out={{"overview",0,0,w,h}};
    std::string layout=o.layout;
    if(layout=="smart")layout=o.preset=="fast"?"overview":o.preset=="detail"?"grid":(o.preset=="text"||std::max(w,h)>o.edge)?"halves":"overview";
    if(layout=="halves"||layout=="all"){
        if(h>=w){int n=(h+1)/2,over=std::max(1,h/20);out.push_back({"top",0,0,w,std::min(h,n+over)});out.push_back({"bottom",0,std::max(0,n-over),w,h-std::max(0,n-over)});}
        else{int n=(w+1)/2,over=std::max(1,w/20);out.push_back({"left",0,0,std::min(w,n+over),h});out.push_back({"right",std::max(0,n-over),0,w-std::max(0,n-over),h});}}
    if(layout=="grid"||layout=="all")for(int y=0;y<2;y++)for(int x=0;x<2;x++){
        int x0=x*w/2,y0=y*h/2,x1=(x+1)*w/2,y1=(y+1)*h/2;
        if(x1>x0&&y1>y0)out.push_back({"grid-"+std::to_string(y)+std::to_string(x),x0,y0,x1-x0,y1-y0});}
    if(layout=="strips"||layout=="all"){
        bool vert=h>=w;int length=vert?h:w;int count=std::min(4,std::max(2,int(std::ceil(double(length)/(vert?w:h)))));
        for(int k=0;k<count;k++){int start=k*length/count,end=(k+1)*length/count;
            out.push_back({"strip-"+std::to_string(k),vert?0:start,vert?start:0,vert?w:end-start,vert?end-start:h});}}
    return out;
}
struct Encoded{Bytes data;int w,h,quality;};
void jpeg_write(void* ctx,void* bytes,int n){auto& o=*(Bytes*)ctx;auto p=(unsigned char*)bytes;o.insert(o.end(),p,p+n);}
Encoded encode(const Raster& r,const Region& v,const Options& o){
    double scale=std::min(1.0,double(o.edge)/std::max(v.w,v.h));
    int w=std::max(1,int(v.w*scale)),h=std::max(1,int(v.h*scale));
    for(int attempt=0;attempt<40;attempt++){
        Bytes resized(size_t(w)*h*3);const auto* start=&r.rgb[(size_t(v.y)*r.w+v.x)*3];
        need(stbir_resize_uint8_linear(start,v.w,v.h,r.w*3,resized.data(),w,h,w*3,STBIR_RGB)!=nullptr,"resize_failed");
        for(int quality:{85,75,65,55,45,35}){Bytes bytes;bytes.reserve(size_t(o.cap)*2);
            need(stbi_write_jpg_to_func(jpeg_write,&bytes,w,h,3,resized.data(),quality)!=0,"jpeg_encode_failed");
            if(bytes.size()<=size_t(o.cap))return {std::move(bytes),w,h,quality};}
        w=std::max(1,w*4/5);h=std::max(1,h*4/5);
    }
    throw Failure("proxy_cap_convergence_failed");
}
void publish(const fs::path& p,const unsigned char* bytes,size_t n){
#ifdef _WIN32
    int fd=_wopen(p.c_str(),_O_WRONLY|_O_CREAT|_O_EXCL|_O_BINARY,_S_IREAD|_S_IWRITE);
    need(fd>=0,"exclusive_output_open_failed");FILE* f=_fdopen(fd,"wb");if(!f){_close(fd);throw Failure("output_stream_failed");}
#else
    int fd=open(p.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);
    need(fd>=0,"exclusive_output_open_failed");FILE* f=fdopen(fd,"wb");if(!f){close(fd);throw Failure("output_stream_failed");}
#endif
    bool ok=std::fwrite(bytes,1,n,f)==n;ok=(std::fclose(f)==0)&&ok;need(ok,"short_output_write");need(fs::file_size(p)==n,"output_size_mismatch");
}
void publish(const fs::path& p,const std::string& text){publish(p,(const unsigned char*)text.data(),text.size());}
std::string process(const fs::path& source,const fs::path& out,const Options& o){
    auto begin=Clock::now();auto path=fs::absolute(source).lexically_normal();need(fs::is_regular_file(path),"source_not_regular_file");
    auto before_size=fs::file_size(path);auto before_time=fs::last_write_time(path);Bytes bytes=read_file(path,o.input_bytes);
    int rotation=1;std::string mapping="standard_8bit_display";auto raster=decode(bytes,o,rotation,mapping);bytes.clear();bytes.shrink_to_fit();
    auto decoded=Clock::now();auto chosen=regions(raster.w,raster.h,o);
    if(o.has_crop){need(o.crop[2]>0&&o.crop[3]>0&&uint64_t(o.crop[0])+o.crop[2]<=uint64_t(raster.w)&&uint64_t(o.crop[1])+o.crop[3]<=uint64_t(raster.h),"crop_outside_oriented_source");chosen={{"crop",o.crop[0],o.crop[1],o.crop[2],o.crop[3]}};}
    need(fs::file_size(path)==before_size&&fs::last_write_time(path)==before_time,"source_changed_during_decode");
    need(fs::create_directory(out),"output_directory_exists");
    std::ostringstream files;uint64_t total=0;
    for(size_t i=0;i<chosen.size();i++){const auto& part=chosen[i];auto encoded=encode(raster,part,o);auto p=out/(part.name+".jpg");
        need(encoded.data.size()<=size_t(o.cap),"proxy_byte_cap_failed");publish(p,encoded.data.data(),encoded.data.size());
        if(i)files<<',';files<<"{\"name\":"<<quoted(part.name)<<",\"path\":"<<quoted(utf8(p))<<",\"crop\":["<<part.x<<','<<part.y<<','<<part.w<<','<<part.h
            <<"],\"dimensions\":["<<encoded.w<<','<<encoded.h<<"],\"bytes\":"<<encoded.data.size()<<",\"encoded_base64_bytes\":"<<4*((encoded.data.size()+2)/3)<<",\"quality\":"<<encoded.quality<<'}';total+=encoded.data.size();}
    need(fs::file_size(path)==before_size&&fs::last_write_time(path)==before_time,"source_changed_before_manifest");
    auto done=Clock::now();double decode_ms=std::chrono::duration<double,std::milli>(decoded-begin).count();double total_ms=std::chrono::duration<double,std::milli>(done-begin).count();
    std::string decode_args;
    auto keep=[&](const std::string& key,const std::string& value){decode_args+=","+quoted(key)+","+quoted(value);};
    if(o.mode!="auto")keep("--mode",o.mode);
    if(o.width)keep("--width",std::to_string(o.width));if(o.height)keep("--height",std::to_string(o.height));
    if(o.offset)keep("--offset",std::to_string(o.offset));if(o.stride)keep("--stride",std::to_string(o.stride));
    if(o.trailing)decode_args+=",\"--allow-trailing\"";
    keep("--max-input-pixels",std::to_string(o.pixels));keep("--max-input-bytes",std::to_string(o.input_bytes));
    if(o.has_crop){decode_args+=",\"--crop\"";for(int v:o.crop)decode_args+=","+quoted(std::to_string(v));}
    auto recipe=[&](const std::string& label,const std::string& preset,const std::string& layout){return "{\"label\":"+quoted(label)+",\"command_argv\":["+quoted(utf8(fs::absolute(fs::u8path(o.entry))))+","+quoted(utf8(path))+",\"--preset\","+quoted(preset)+",\"--layout\","+quoted(layout)+decode_args+"]}";};
    std::ostringstream meta;meta<<"{\"engine\":\"native-cpp\",\"version\":\"2.0\",\"source\":"<<quoted(utf8(path))<<",\"source_bytes\":"<<before_size
        <<",\"oriented_dimensions\":["<<raster.w<<','<<raster.h<<"],\"orientation\":"<<rotation<<",\"display_mapping\":"<<quoted(mapping)
        <<",\"preset\":"<<quoted(o.preset)<<",\"max_bytes_each\":"<<o.cap<<",\"max_edge\":"<<o.edge<<",\"output_directory\":"<<quoted(utf8(out))
        <<",\"decode_ms\":"<<decode_ms<<",\"total_ms\":"<<total_ms<<",\"total_proxy_bytes\":"<<total<<",\"proxies\":["<<files.str()<<"]"
        <<",\"ready_recipes\":["<<recipe("fast overview","fast","overview")<<','<<recipe("overlapping halves","text","halves")<<','<<recipe("four details","detail","grid")<<','<<recipe("long screenshot strips","text","strips")<<"]}";
    publish(out/"manifest.json",meta.str()+"\n");return meta.str();
}
int run(const std::vector<std::string>& args){
    if(args.size()==2&&(args[1]=="--help"||args[1]=="--version")){
        std::cout<<"{\"program\":\"image-proxy-native\",\"version\":\"2.0\",\"usage\":\"proxy INPUT [INPUT...] [--out-dir NEWDIR] [--preset fast|balanced|text|detail] [--layout smart|overview|halves|grid|strips|all] [--crop X Y WIDTH HEIGHT]\",\"default_max_bytes\":240000,\"default_max_edge\":1600}\n";return 0;}
    Options o=parse(args);
    if(o.frame!=0||!o.fallback_args.empty()||o.mode=="camera-raw"||o.mode=="video")throw Failure("decoder_needs_python_fallback",78);
    for(const auto& p:o.input){auto ext=p.extension().string();std::transform(ext.begin(),ext.end(),ext.begin(),[](unsigned char c){return char(std::tolower(c));});
        if(o.mode=="auto"&&(ext==".raw"||ext==".bin"))throw Failure("raw_requires_explicit_layout_and_geometry");}
    if(o.out.empty())o.out=fs::temp_directory_path()/("codex-image-proxy-"+std::to_string(std::chrono::system_clock::now().time_since_epoch().count()));
    o.out=fs::absolute(o.out).lexically_normal();
    // Do not publish native output before deciding that every input is native-decodable.
    if(o.input.size()>1&&o.mode.rfind("raw-",0)!=0)for(auto& p:o.input){auto b=read_file(p,o.input_bytes);int w,h,c;
        if(!stbi_info_from_memory(b.data(),int(b.size()),&w,&h,&c)||stbi_is_16_bit_from_memory(b.data(),int(b.size())))throw Failure("batch_needs_python_fallback",78);}
    if(!o.out.parent_path().empty())fs::create_directories(o.out.parent_path());
    if(o.input.size()>1)need(fs::create_directory(o.out),"batch_output_directory_exists");
    std::ostringstream result;result<<"{\"engine\":\"native-cpp\",\"items\":[";
    for(size_t i=0;i<o.input.size();i++){if(i)result<<',';result<<process(o.input[i],o.input.size()==1?o.out:o.out/std::to_string(i+1),o);}
    std::cout<<result.str()<<"]}\n";return 0;
}
int main(int argc,char** argv){
    try {std::vector<std::string> args;
#ifdef _WIN32
        int count=0;auto wide=CommandLineToArgvW(GetCommandLineW(),&count);need(wide!=nullptr,"unicode_arguments_failed");
        for(int i=0;i<count;i++){int n=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,wide[i],-1,nullptr,0,nullptr,nullptr);need(n>0,"invalid_unicode_argument");std::string s(n,'\0');WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,wide[i],-1,s.data(),n,nullptr,nullptr);s.pop_back();args.push_back(std::move(s));}LocalFree(wide);
#else
        for(int i=0;i<argc;i++)args.emplace_back(argv[i]);
#endif
        return run(args);
    }catch(const Failure& e){std::cerr<<"{\"ready\":false,\"fallback_required\":"<<(e.code==78?"true":"false")<<",\"error\":"<<quoted(e.what())<<"}\n";return e.code;}
    catch(const std::exception& e){std::cerr<<"{\"ready\":false,\"error\":"<<quoted(e.what())<<"}\n";return 2;}
}
