#!/usr/bin/env python3
"""Linux/Mesa differential raster validation (NumPy + system libEGL/libGL).

Compiles mechanically translated GLSL helper bodies, NOT Unity HLSL. No timings
are taken: software rasterization is not evidence of hardware GPU performance.
"""
import argparse
import ctypes as c
import hashlib
import itertools
import json
from pathlib import Path
import numpy as np
from gpu_lab import programs, TRANSFORMS, UNIFORMS
from validate import HEADER


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,default=Path(__file__).parent/'results/glsl-results.json')
    args=ap.parse_args(); sources=programs()
    egl=c.CDLL('libEGL.so.1'); gl=c.CDLL('libGL.so.1')
    P,I,U,F=c.c_void_p,c.c_int,c.c_uint,c.c_float
    def fn(lib,name,ret,*types):
        f=getattr(lib,name);f.restype=ret;f.argtypes=types;return f
    def need(result,label):
        if not result:raise RuntimeError(label+' failed')
        return result
    display=need(fn(egl,'eglGetPlatformDisplay',P,U,P,c.POINTER(I))(0x31DD,None,None),'display')
    major,minor=I(),I()
    need(fn(egl,'eglInitialize',U,P,c.POINTER(I),c.POINTER(I))(display,c.byref(major),c.byref(minor)),'initialize')
    need(fn(egl,'eglBindAPI',U,U)(0x30A2),'bind OpenGL')
    attrs=(I*11)(0x3033,1,0x3040,8,0x3024,8,0x3023,8,0x3022,8,0x3038); config,count=P(),I()
    need(fn(egl,'eglChooseConfig',U,P,c.POINTER(I),c.POINTER(P),I,c.POINTER(I))(display,attrs,c.byref(config),1,c.byref(count)),'config')
    need(count.value,'available config'); ca=(I*7)(0x3098,3,0x30FB,3,0x30FD,1,0x3038)
    ctx=need(fn(egl,'eglCreateContext',P,P,P,P,c.POINTER(I))(display,config,None,ca),'context')
    need(fn(egl,'eglMakeCurrent',U,P,P,P,P)(display,None,None,ctx),'current context')
    specs={
        'GetString':(c.c_char_p,U),'GetError':(U,),
        'CreateShader':(U,U),'ShaderSource':(None,U,I,c.POINTER(c.c_char_p),c.POINTER(I)),
        'CompileShader':(None,U),'GetShaderiv':(None,U,U,c.POINTER(I)),
        'GetShaderInfoLog':(None,U,I,c.POINTER(I),c.c_char_p),
        'CreateProgram':(U,),'AttachShader':(None,U,U),'LinkProgram':(None,U),
        'GetProgramiv':(None,U,U,c.POINTER(I)),'GetProgramInfoLog':(None,U,I,c.POINTER(I),c.c_char_p),
        'UseProgram':(None,U),'GetUniformLocation':(I,U,c.c_char_p),
        'Uniform1i':(None,I,I),'Uniform1f':(None,I,F),'Uniform2f':(None,I,F,F),'Uniform4f':(None,I,F,F,F,F),
        'GenVertexArrays':(None,I,c.POINTER(U)),'BindVertexArray':(None,U),
        'GenBuffers':(None,I,c.POINTER(U)),'BindBuffer':(None,U,U),'BufferData':(None,U,c.c_ssize_t,P,U),
        'EnableVertexAttribArray':(None,U),'VertexAttribPointer':(None,U,I,U,c.c_ubyte,I,P),
        'GenTextures':(None,I,c.POINTER(U)),'BindTexture':(None,U,U),'TexImage2D':(None,U,I,I,I,I,I,U,U,P),
        'TexParameteri':(None,U,U,I),'GenFramebuffers':(None,I,c.POINTER(U)),'BindFramebuffer':(None,U,U),
        'FramebufferTexture2D':(None,U,U,U,U,I),'CheckFramebufferStatus':(U,U),
        'Viewport':(None,I,I,I,I),'Disable':(None,U),'Enable':(None,U),'BlendFunc':(None,U,U),
        'ClearColor':(None,F,F,F,F),'Clear':(None,U),'DrawArrays':(None,U,I,I),
        'ReadPixels':(None,I,I,I,I,U,U,P),
    }
    functions={n:fn(gl,'gl'+n,*t) for n,t in specs.items()}
    def call(name,*args):return functions[name](*args)
    def compile_shader(stage,source):
        sid=call('CreateShader',0x8B31 if stage=='vertex' else 0x8B30)
        text=c.c_char_p(source.encode());call('ShaderSource',sid,1,c.byref(text),None)
        call('CompileShader',sid);ok=I();call('GetShaderiv',sid,0x8B81,c.byref(ok))
        if not ok.value:
            log=c.create_string_buffer(16384);call('GetShaderInfoLog',sid,len(log),None,log)
            raise RuntimeError(log.value.decode()+'\n'+source)
        return sid
    compiled={};es100=0
    for item in sources:
        p=call('CreateProgram')
        for stage in ['vertex','fragment']:
            call('AttachShader',p,compile_shader(stage,item[stage]))
            if item['kind']!='native':
                s=item[stage].replace('#version 300 es','#version 100')
                s=s.replace('layout(location=0) in vec2 aPos;','attribute vec2 aPos;')
                if stage=='vertex':s=s.replace('out vec','varying vec')
                else:s=s.replace('in vec','varying vec').replace('out vec4 outColor;','').replace('outColor=color;','gl_FragColor=color;').replace('texture(','texture2D(')
                compile_shader(stage,s);es100+=1
        call('LinkProgram',p);ok=I();call('GetProgramiv',p,0x8B82,c.byref(ok))
        if not ok.value:
            log=c.create_string_buffer(16384);call('GetProgramInfoLog',p,len(log),None,log)
            raise RuntimeError(log.value.decode())
        compiled[(item['kind'],item['clip'],item['alpha'])]=(p,{n:call('GetUniformLocation',p,n.encode()) for n in UNIFORMS})
    def gen(kind):
        v=U();call('Gen'+kind,1,c.byref(v));return v.value
    call('BindVertexArray',gen('VertexArrays'));call('BindBuffer',0x8892,gen('Buffers'))
    vertices=np.array([0,0,1,0,0,1,0,1,1,0,1,1],dtype=np.float32)
    call('BufferData',0x8892,vertices.nbytes,vertices.ctypes.data,0x88E4)
    call('EnableVertexAttribArray',0);call('VertexAttribPointer',0,2,0x1406,0,0,None)
    atlas=gen('Textures');call('BindTexture',0x0DE1,atlas)
    for n,v in [(0x2801,0x2600),(0x2800,0x2600),(0x2802,0x812F),(0x2803,0x812F)]:call('TexParameteri',0x0DE1,n,v)
    width,height=2056,64;target=gen('Textures');call('BindTexture',0x0DE1,target)
    call('TexImage2D',0x0DE1,0,0x8058,width,height,0,0x1908,0x1401,None)
    call('BindFramebuffer',0x8D40,gen('Framebuffers'));call('FramebufferTexture2D',0x8D40,0x8CE0,0x0DE1,target,0)
    if call('CheckFramebufferStatus',0x8D40)!=0x8CD5:raise RuntimeError('Incomplete framebuffer')
    call('Viewport',0,0,width,height)
    # R8 NPOT rows need byte alignment, not OpenGL's default four-byte row alignment.
    fn(gl,'glPixelStorei',None,U,I)(0x0CF5,1)
    def render(kind,aw,fmt,mode,clip,alpha,tr,blend):
        p,u=compiled[(kind,clip,alpha)];call('UseProgram',p);call('BindTexture',0x0DE1,atlas)
        call('Uniform1i',u['uAtlas'],0);call('Uniform1f',u['uFormat'],fmt);call('Uniform1f',u['uMode'],mode)
        call('Uniform4f',u['uTexelSize'],1/aw,1/4,aw,4);call('Uniform2f',u['uRange'],aw*(8 if fmt else 4),4)
        off,m,t,pr=TRANSFORMS[tr]
        for n,v in [('uOffset',off),('uTranslate',t),('uPerspective',pr)]:call('Uniform2f',u[n],*v)
        call('Uniform4f',u['uTransform'],*m)
        for cap in [0x0BD0,0x0B71,0x0B90,0x0C11,0x0B44]:call('Disable',cap)
        if blend:call('Enable',0x0BE2);call('BlendFunc',0x0302,0x0303)
        else:call('Disable',0x0BE2)
        call('ClearColor',.125,.25,.375,.5);call('Clear',0x4000);call('DrawArrays',4,0,6)
        if blend:call('DrawArrays',4,0,6)
        pixels=np.empty((height,width,4),dtype=np.uint8);call('ReadPixels',0,0,width,height,0x1908,0x1401,pixels.ctypes.data)
        error=call('GetError')
        if error:raise RuntimeError(f'GL error {error}')
        return pixels
    comparisons=cases=bad=0;first=None
    for aw in [256,257]:
        data=np.array([[(x+y*37)&255 for x in range(aw)] for y in range(4)],dtype=np.uint8)
        call('BindTexture',0x0DE1,atlas);call('TexImage2D',0x0DE1,0,0x8229,aw,4,0,0x1903,0x1401,data.ctypes.data)
        for fmt,mode,clip,alpha,tr,blend in itertools.product(range(2),range(3),range(2),range(2),range(3),range(2)):
            ref=render('legacy',aw,fmt,mode,clip,alpha,tr,blend)
            for kind in ['portable','native']:
                now=render(kind,aw,fmt,mode,clip,alpha,tr,blend);neq=ref!=now;count=int(neq.sum())
                cases+=1;comparisons+=now.size;bad+=count
                if count and first is None:
                    ix=tuple(int(x) for x in np.argwhere(neq)[0])
                    first=dict(kind=kind,atlasWidth=aw,format=fmt,mode=mode,clip=clip,alpha=alpha,transform=tr,blend=blend,index=ix,expected=int(ref[ix]),actual=int(now[ix]))
    report=dict(candidate_sha256=hashlib.sha256(HEADER.read_bytes()).hexdigest(),
        programs_sha256=hashlib.sha256(json.dumps(sources,sort_keys=True).encode()).hexdigest(),
        scope='Mechanically translated GLSL rasterization; NOT Unity/HLSL compiler or browser execution',
        renderer=call('GetString',0x1F01).decode(),version=call('GetString',0x1F02).decode(),
        GLSL_ES_300_programs_linked=len(compiled),GLSL_ES_100_shaders_compiled=es100,
        render_cases=cases,RGBA8_channel_comparisons=comparisons,mismatched_channels=bad,
        first_mismatch=first,status='FAIL' if bad else 'PASS',performance_measurement='NOT_MEASURED: software correctness test, no hardware timing')
    args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    fn(egl,'eglMakeCurrent',U,P,P,P,P)(display,None,None,None)
    fn(egl,'eglDestroyContext',U,P,P)(display,ctx);fn(egl,'eglTerminate',U,P)(display)
    if bad:raise SystemExit(1)

if __name__=='__main__': main()
