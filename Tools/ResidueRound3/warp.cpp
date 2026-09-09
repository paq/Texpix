// D3D11 WARP correctness only. No hardware performance claims or timing.
#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
using Microsoft::WRL::ComPtr;
namespace fs=std::filesystem;
void check(HRESULT hr){if(FAILED(hr))throw std::runtime_error("D3D11 failure: "+std::to_string((unsigned)hr));}
std::vector<char> read(const fs::path& p){std::ifstream f(p,std::ios::binary);if(!f)throw std::runtime_error("Missing "+p.string());return {std::istreambuf_iterator<char>(f),{}};}
struct V{float pos[4],color[4],uv[4];};
struct C{float ts[4],rect[4],matrix[16],flags[4];};
struct Case{float data[4],fill[4],outline[4],extra[4];};
static_assert(sizeof(C)==112 && sizeof(Case)==64 && sizeof(V)==48,"Shader layout mismatch");
int main(int argc,char**argv){try{
    fs::path root=argc>1?argv[1]:"round3-results";
    ComPtr<ID3D11Device> dev;ComPtr<ID3D11DeviceContext> ctx;D3D_FEATURE_LEVEL level;
    check(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_WARP,nullptr,0,nullptr,0,D3D11_SDK_VERSION,&dev,&level,&ctx));
    std::cout<<"DEVICE D3D11 WARP software; hardware timing NOT_MEASURED\n";
    auto buffer=[&](UINT bytes,UINT bind,UINT misc,UINT stride,const void* data,D3D11_USAGE usage=D3D11_USAGE_DEFAULT,UINT cpu=0){
        D3D11_BUFFER_DESC d={};d.ByteWidth=bytes;d.BindFlags=bind;d.MiscFlags=misc;d.StructureByteStride=stride;d.Usage=usage;d.CPUAccessFlags=cpu;
        D3D11_SUBRESOURCE_DATA init={};init.pSysMem=data;ComPtr<ID3D11Buffer>b;check(dev->CreateBuffer(&d,data?&init:nullptr,&b));return b;
    };
    auto constants=buffer(sizeof(C),D3D11_BIND_CONSTANT_BUFFER,0,0,nullptr);
    ID3D11Buffer* cb=constants.Get();ctx->VSSetConstantBuffers(0,1,&cb);ctx->PSSetConstantBuffers(0,1,&cb);ctx->CSSetConstantBuffers(0,1,&cb);
    D3D11_SAMPLER_DESC sd={};sd.Filter=D3D11_FILTER_MIN_MAG_MIP_POINT;sd.AddressU=sd.AddressV=sd.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;sd.MaxLOD=D3D11_FLOAT32_MAX;sd.ComparisonFunc=D3D11_COMPARISON_NEVER;
    ComPtr<ID3D11SamplerState> samp;check(dev->CreateSamplerState(&sd,&samp));ID3D11SamplerState*ss=samp.Get();ctx->PSSetSamplers(0,1,&ss);ctx->CSSetSamplers(0,1,&ss);
    C c={};c.rect[0]=c.rect[1]=0;c.rect[2]=.72f;c.rect[3]=.82f;c.flags[0]=1;
    ComPtr<ID3D11Texture2D> atlas;ComPtr<ID3D11ShaderResourceView> av;
    auto setAtlas=[&](int w){
        std::vector<unsigned char>a(w*4);for(int y=0;y<4;++y)for(int x=0;x<w;++x)a[y*w+x]=(x+37*y)&255;
        D3D11_TEXTURE2D_DESC d={};d.Width=w;d.Height=4;d.MipLevels=d.ArraySize=1;d.Format=DXGI_FORMAT_R8_UNORM;d.SampleDesc.Count=1;d.BindFlags=D3D11_BIND_SHADER_RESOURCE;
        D3D11_SUBRESOURCE_DATA init={a.data(),(UINT)w,0};atlas.Reset();av.Reset();check(dev->CreateTexture2D(&d,&init,&atlas));check(dev->CreateShaderResourceView(atlas.Get(),nullptr,&av));
        ID3D11ShaderResourceView*v=av.Get();ctx->PSSetShaderResources(0,1,&v);ctx->CSSetShaderResources(0,1,&v);
        c.ts[0]=1.f/w;c.ts[1]=.25f;c.ts[2]=(float)w;c.ts[3]=4;
    };
    setAtlas(257);
    std::mt19937 rng(0x54455833);std::uniform_real_distribution<float> unit(0,1);
    std::vector<Case> cases;
    auto add=[&](float x,float y,int mode,int fmt,float error,int jitter){
        Case v={};v.data[0]=x;v.data[1]=y;v.data[2]=(float)mode;v.data[3]=(float)fmt;
        for(int k=0;k<4;++k){v.fill[k]=unit(rng);v.outline[k]=unit(rng);}
        v.extra[0]=(float)(rng()%65536);v.extra[1]=(float)(rng()%1048576);v.extra[2]=error;v.extra[3]=(float)jitter;cases.push_back(v);
    };
    for(int fmt=0;fmt<2;++fmt)for(int byte=0;byte<256;++byte)for(int sub=0;sub<(fmt?8:4);++sub)for(int mode=0;mode<4;++mode){
        float x=(float)(byte*(fmt?8:4)+sub);
        for(float off:{0.f,.125f,.5f,.875f})for(float error:{-.49f,0.f,.49f})for(int j:{-1,0,1})add(x+off,.5f,mode,fmt,error,j);
        if(x>0)add(std::nextafter(x,0.f),.5f,mode,fmt,0,0);
        add(std::nextafter(x,INFINITY),.5f,mode,fmt,0,0);
    }
    for(int n=0;n<100000;++n){int fmt=rng()%2;float x=unit(rng)*131072.f;add(x,unit(rng)*12.f,rng()%4,fmt,(n%3-1)*.49f,n%3-1);}
    auto input=buffer((UINT)(cases.size()*sizeof(Case)),D3D11_BIND_SHADER_RESOURCE,D3D11_RESOURCE_MISC_BUFFER_STRUCTURED,sizeof(Case),cases.data());
    auto output=buffer((UINT)(cases.size()*16),D3D11_BIND_UNORDERED_ACCESS,D3D11_RESOURCE_MISC_BUFFER_STRUCTURED,16,nullptr);
    auto staging=buffer((UINT)(cases.size()*16),0,0,0,nullptr,D3D11_USAGE_STAGING,D3D11_CPU_ACCESS_READ);
    ComPtr<ID3D11ShaderResourceView>iv;check(dev->CreateShaderResourceView(input.Get(),nullptr,&iv));ID3D11ShaderResourceView*ip=iv.Get();ctx->CSSetShaderResources(1,1,&ip);
    ComPtr<ID3D11UnorderedAccessView>ov;check(dev->CreateUnorderedAccessView(output.Get(),nullptr,&ov));ID3D11UnorderedAccessView*op=ov.Get();ctx->CSSetUnorderedAccessViews(0,1,&op,nullptr);
    uint64_t scalarBad=0,unpackBad=0,oracleBad=0,signatureBad=0;
    for(int gamma=0;gamma<2;++gamma){
        auto bytes=read(root/("cs-g"+std::to_string(gamma)+".dxbc"));ComPtr<ID3D11ComputeShader>cs;check(dev->CreateComputeShader(bytes.data(),bytes.size(),nullptr,&cs));ctx->CSSetShader(cs.Get(),nullptr,0);
        const UINT sentinel[4]={0xdeadbeefu,0xdeadbeefu,0xdeadbeefu,0xdeadbeefu};
        ctx->ClearUnorderedAccessViewUint(ov.Get(),sentinel);
        c.flags[1]=(float)cases.size();ctx->UpdateSubresource(constants.Get(),0,nullptr,&c,0,0);ctx->Dispatch((UINT)(cases.size()+63)/64,1,1);ctx->CopyResource(staging.Get(),output.Get());
        D3D11_MAPPED_SUBRESOURCE map;check(ctx->Map(staging.Get(),0,D3D11_MAP_READ,0,&map));auto p=(const uint32_t*)map.pData;
        for(size_t i=0;i<cases.size();++i){
            scalarBad+=p[i*4];unpackBad+=p[i*4+1];oracleBad+=p[i*4+2];
            const auto& v=cases[i];
            int tx=std::clamp((int)std::floor(v.data[0]/(v.data[3]>=.5f?8.f:4.f)),0,256);
            int ty=std::clamp((int)std::floor(v.data[1]),0,3);
            uint32_t sampledByte=(uint32_t)((tx+37*ty)&255);
            uint32_t expectedSignature=(uint32_t)i ^ 0x54585033u ^ (sampledByte<<20u);
            signatureBad+=(p[i*4+3]!=expectedSignature);
            if((p[i*4]||p[i*4+1]||p[i*4+2])&&scalarBad+unpackBad+oracleBad<4)
                std::cout<<"FIRST COMPUTE "<<i<<" x="<<v.data[0]<<" mode="<<v.data[2]<<" fmt="<<v.data[3]<<" flags="<<p[i*4]<<","<<p[i*4+1]<<","<<p[i*4+2]<<"\n";
        }
        ctx->Unmap(staging.Get(),0);
    }
    ctx->CSSetShader(nullptr,nullptr,0);op=nullptr;ctx->CSSetUnorderedAccessViews(0,1,&op,nullptr);
    std::cout<<"COMPUTE cases_per_colorspace="<<cases.size()<<" colorspaces=2 differential_bad="<<scalarBad<<" unpack_bad="<<unpackBad<<" oracle_bad="<<oracleBad<<" signature_bad="<<signatureBad<<"\n";
    const int W=2056,H=16;
    D3D11_TEXTURE2D_DESC td={};td.Width=W;td.Height=H;td.MipLevels=td.ArraySize=1;td.Format=DXGI_FORMAT_R8G8B8A8_UNORM;td.SampleDesc.Count=1;td.BindFlags=D3D11_BIND_RENDER_TARGET;
    ComPtr<ID3D11Texture2D>rt,rb;check(dev->CreateTexture2D(&td,nullptr,&rt));ComPtr<ID3D11RenderTargetView>rv;check(dev->CreateRenderTargetView(rt.Get(),nullptr,&rv));ID3D11RenderTargetView*r=rv.Get();ctx->OMSetRenderTargets(1,&r,nullptr);
    td.BindFlags=0;td.Usage=D3D11_USAGE_STAGING;td.CPUAccessFlags=D3D11_CPU_ACCESS_READ;check(dev->CreateTexture2D(&td,nullptr,&rb));
    D3D11_VIEWPORT vp={0,0,(float)W,(float)H,0,1};ctx->RSSetViewports(1,&vp);
    D3D11_RASTERIZER_DESC rsd={};rsd.FillMode=D3D11_FILL_SOLID;rsd.CullMode=D3D11_CULL_NONE;rsd.DepthClipEnable=TRUE;ComPtr<ID3D11RasterizerState>rs;check(dev->CreateRasterizerState(&rsd,&rs));ctx->RSSetState(rs.Get());
    D3D11_DEPTH_STENCIL_DESC dd={};dd.DepthEnable=FALSE;dd.DepthFunc=D3D11_COMPARISON_ALWAYS;ComPtr<ID3D11DepthStencilState>ds;check(dev->CreateDepthStencilState(&dd,&ds));ctx->OMSetDepthStencilState(ds.Get(),0);
    ComPtr<ID3D11BlendState> blend[2];for(int b=0;b<2;++b){D3D11_BLEND_DESC d={};auto&x=d.RenderTarget[0];x.BlendEnable=b;x.SrcBlend=x.SrcBlendAlpha=D3D11_BLEND_SRC_ALPHA;x.DestBlend=x.DestBlendAlpha=D3D11_BLEND_INV_SRC_ALPHA;x.BlendOp=x.BlendOpAlpha=D3D11_BLEND_OP_ADD;x.RenderTargetWriteMask=D3D11_COLOR_WRITE_ENABLE_ALL;check(dev->CreateBlendState(&d,&blend[b]));}
    ComPtr<ID3D11VertexShader>vs[2][2];ComPtr<ID3D11PixelShader>ps[2][2][2][2];ComPtr<ID3D11InputLayout>layout;
    for(int f=0;f<2;++f)for(int g=0;g<2;++g){
        auto bytes=read(root/("vs-f"+std::to_string(f)+"-g"+std::to_string(g)+"-r0-a0.dxbc"));check(dev->CreateVertexShader(bytes.data(),bytes.size(),nullptr,&vs[f][g]));
        if(!layout){D3D11_INPUT_ELEMENT_DESC e[]={{"POSITION",0,DXGI_FORMAT_R32G32B32A32_FLOAT,0,0,D3D11_INPUT_PER_VERTEX_DATA,0},{"COLOR",0,DXGI_FORMAT_R32G32B32A32_FLOAT,0,16,D3D11_INPUT_PER_VERTEX_DATA,0},{"TEXCOORD",0,DXGI_FORMAT_R32G32B32A32_FLOAT,0,32,D3D11_INPUT_PER_VERTEX_DATA,0}};check(dev->CreateInputLayout(e,3,bytes.data(),bytes.size(),&layout));}
        for(int cr=0;cr<2;++cr)for(int ac=0;ac<2;++ac){bytes=read(root/("ps-f"+std::to_string(f)+"-g"+std::to_string(g)+"-r"+std::to_string(cr)+"-a"+std::to_string(ac)+".dxbc"));check(dev->CreatePixelShader(bytes.data(),bytes.size(),nullptr,&ps[f][g][cr][ac]));}
    }
    ctx->IASetInputLayout(layout.Get());ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    uint64_t comparisons=0,channels=0,bad=0,uniformImages=0;
    uint64_t minimumDistinctPixels=std::numeric_limits<uint64_t>::max();
    for(int aw:{256,257}){setAtlas(aw);
    for(int fmt=0;fmt<2;++fmt)for(int mode=0;mode<4;++mode)for(int grid:{1,32}){
        std::vector<V>vertices;
        for(int cell=0;cell<grid;++cell){float l=(float)cell/grid,h=(float)(cell+1)/grid;float xy[][2]={{l,0},{h,0},{l,1},{l,1},{h,0},{h,1}};
            for(auto&t:xy){V v={};v.pos[0]=2*t[0]-1;v.pos[1]=2*t[1]-1;v.pos[3]=1;v.color[0]=.25f+.5f*t[0];v.color[1]=.5f;v.color[2]=1-.5f*t[1];v.color[3]=.625f;
                v.uv[0]=t[0]*aw*(fmt?8:4);v.uv[1]=t[1]*4;v.uv[2]=192*256+32;v.uv[3]=(float)(fmt*262144+128*1024+96*4+mode);vertices.push_back(v);}}
        auto vb=buffer((UINT)(vertices.size()*sizeof(V)),D3D11_BIND_VERTEX_BUFFER,0,0,vertices.data());ID3D11Buffer*v=vb.Get();UINT stride=sizeof(V),off=0;ctx->IASetVertexBuffers(0,1,&v,&stride,&off);
        for(int tr=0;tr<3;++tr){std::fill(c.matrix,c.matrix+16,0.f);c.matrix[10]=c.matrix[15]=1;c.matrix[0]=c.matrix[5]=1;
            if(tr){c.matrix[0]=.85f;c.matrix[5]=.87f;c.matrix[1]=.18f;c.matrix[4]=-.13f;c.matrix[12]=.013f;c.matrix[13]=-.021f;}
            if(tr==2){c.matrix[3]=.15f;c.matrix[7]=-.08f;}
            for(int g=0;g<2;++g)for(int cr=0;cr<2;++cr)for(int ac=0;ac<2;++ac)for(int b=0;b<2;++b)for(int convert=0;convert<2;++convert){
                c.flags[0]=(float)convert;ctx->UpdateSubresource(constants.Get(),0,nullptr,&c,0,0);ctx->OMSetBlendState(blend[b].Get(),nullptr,0xffffffffu);
                std::vector<uint8_t> ref(W*H*4);
                for(int f=0;f<2;++f){
                    float clear[]={.125f,.25f,.375f,.5f};ctx->ClearRenderTargetView(rv.Get(),clear);
                    ctx->VSSetShader(vs[f][g].Get(),nullptr,0);ctx->PSSetShader(ps[f][g][cr][ac].Get(),nullptr,0);
                    ctx->Draw((UINT)vertices.size(),0);if(b)ctx->Draw((UINT)vertices.size(),0);
                    ctx->CopyResource(rb.Get(),rt.Get());D3D11_MAPPED_SUBRESOURCE map;check(ctx->Map(rb.Get(),0,D3D11_MAP_READ,0,&map));
                    uint64_t distinct=0;auto first=(const uint8_t*)map.pData;
                    for(int y=0;y<H;++y){
                        auto p=(const uint8_t*)map.pData+y*map.RowPitch;
                        for(int px=0;px<W;++px)distinct+=!std::equal(p+px*4,p+px*4+4,first);
                        for(int x=0;x<W*4;++x){size_t i=(size_t)y*W*4+x;if(!f)ref[i]=p[x];else if(ref[i]!=p[x]){
                            ++bad;if(bad<4)std::cout<<"FIRST RASTER aw="<<aw<<" fmt="<<fmt<<" mode="<<mode<<" grid="<<grid<<" tr="<<tr<<" g="<<g<<" clip="<<cr<<ac<<" blend="<<b<<" convert="<<convert<<" idx="<<i<<" ref="<<(int)ref[i]<<" new="<<(int)p[x]<<"\n";
                        }}
                    }
                    minimumDistinctPixels=std::min(minimumDistinctPixels,distinct);uniformImages+=(distinct==0);
                    ctx->Unmap(rb.Get(),0);
                }
                ++comparisons;channels+=(uint64_t)W*H*4;
            }
        }
    }}
    bool failed=scalarBad||unpackBad||oracleBad||signatureBad||bad||uniformImages;
    std::ofstream report(root/"warp-results.json");
    if(!report)throw std::runtime_error("Could not create result file");
    report<<"{\n  \"device\":\"D3D11 WARP (software)\",\n  \"scope\":\"Actual compiled HLSL helpers; compute probes and VS/PS raster pairs. Not Unity or hardware performance.\",\n  \"compute_cases_per_colorspace\":"<<cases.size()
          <<",\n  \"colorspaces\":2,\n  \"compute_differential_mismatches\":"<<scalarBad
          <<",\n  \"unpack_mismatches\":"<<unpackBad<<",\n  \"integer_oracle_mismatches\":"<<oracleBad
          <<",\n  \"execution_signature_and_sample_mismatches\":"<<signatureBad
          <<",\n  \"raster_cases\":"<<comparisons<<",\n  \"rgba8_channels\":"<<channels
          <<",\n  \"raster_mismatches\":"<<bad<<",\n  \"uniform_render_images\":"<<uniformImages
          <<",\n  \"minimum_pixels_different_from_first\":"<<minimumDistinctPixels
          <<",\n  \"vertex_color_conversion_flags_tested\":[0,1],\n  \"hardware_timing\":\"NOT_MEASURED\",\n  \"status\":\""<<(failed?"FAIL":"PASS")<<"\"\n}\n";
    report.close();std::cout<<std::ifstream(root/"warp-results.json").rdbuf();
    return failed?1:0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
