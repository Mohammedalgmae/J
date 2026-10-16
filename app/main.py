import os, io, uuid, json, urllib.request, urllib.error
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image, ImageDraw, ImageFont
import numpy as np, cv2, pytesseract
from pytesseract import Output

BASE=Path(__file__).resolve().parent.parent
DATA=BASE/'data'; DATA.mkdir(exist_ok=True)
STATIC=BASE/'app'/'static'
app=FastAPI(title='Manga Arabic Translator')
app.mount('/static',StaticFiles(directory=str(STATIC)),name='static')

def meta_path(i): return DATA/f'{i}.json'
def safe_id(i):
    if not i or len(i)>40 or any(c not in '0123456789abcdef-' for c in i): raise HTTPException(400,'معرّف الصورة غير صالح')
    return i
class RenderIn(BaseModel):
    image_id:str
    region_id:str
    text_ar:str=Field(max_length=1000)
    font_size:int=Field(default=24,ge=10,le=100)
    color:str=Field(default='#111111',pattern=r'^#[0-9a-fA-F]{6}$')
class TranslateIn(BaseModel): image_id:str; style:str='natural'

@app.get('/',response_class=HTMLResponse)
def home(): return FileResponse(STATIC/'index.html')
@app.get('/api/health')
def health():
    try: ver=pytesseract.get_tesseract_version(); ocr='Tesseract '+str(ver)
    except Exception: ocr='unavailable'
    return {'ok':True,'ocr_engine':ocr,'translation_provider':'configured' if (os.getenv('GEMINI_API_KEY') or os.getenv('OPENAI_API_KEY')) else 'manual'}

@app.post('/api/upload')
async def upload(file:UploadFile=File(...)):
    if file.content_type not in ('image/png','image/jpeg','image/webp'): raise HTTPException(415,'ارفع صورة PNG أو JPG أو WEBP فقط')
    raw=await file.read()
    if len(raw)>20*1024*1024: raise HTTPException(413,'حجم الصورة يتجاوز 20 ميغابايت')
    try:
        im=Image.open(io.BytesIO(raw)).convert('RGB')
        if im.width*im.height>25_000_000: raise HTTPException(413,'أبعاد الصورة كبيرة جدًا')
    except HTTPException: raise
    except Exception: raise HTTPException(400,'تعذر قراءة الصورة')
    iid=uuid.uuid4().hex; original=DATA/f'{iid}-original.png'; im.save(original)
    try:
        # Block-oriented OCR is less likely to split dialogue into isolated words.
        d=pytesseract.image_to_data(im,lang='eng',output_type=Output.DICT,config='--oem 3 --psm 6')
        line_groups={}
        for k,word in enumerate(d['text']):
            word=word.strip()
            try: conf=float(d['conf'][k])
            except: conf=-1
            if not word or conf<25: continue
            x,y,w,h=[int(d[a][k]) for a in ('left','top','width','height')]
            if w<=0 or h<=0: continue
            key=(d['block_num'][k],d['par_num'][k],d['line_num'][k])
            if key not in line_groups: line_groups[key]={'words':[],'box':[x,y,x+w,y+h],'conf':[]}
            g=line_groups[key]; g['words'].append((x,word)); g['conf'].append(conf)
            b=g['box']; g['box']=[min(b[0],x),min(b[1],y),max(b[2],x+w),max(b[3],y+h)]
        lines=[]
        for g in line_groups.values():
            g['words'].sort(key=lambda z:z[0])
            g['text']=' '.join(z[1] for z in g['words'])
            g['confidence']=sum(g['conf'])/len(g['conf'])
            lines.append(g)
        lines.sort(key=lambda g:(g['box'][1],g['box'][0]))
        # Merge nearby lines when their boxes overlap horizontally and the gap is small.
        groups=[]
        for line in lines:
            x1,y1,x2,y2=line['box']
            best=None
            for group in reversed(groups[-5:]):
                gx1,gy1,gx2,gy2=group['box']
                gap=y1-gy2
                overlap=max(0,min(x2,gx2)-max(x1,gx1))
                denom=max(1,min(x2-x1,gx2-gx1))
                horizontal_overlap=overlap/denom
                height=max(1,max(y2-y1,gy2-gy1))
                center_delta=abs(((x1+x2)/2)-((gx1+gx2)/2))
                if -height*0.15 <= gap <= height*0.8 and horizontal_overlap>=0.60:
                    best=group
                    break
            if best is None:
                groups.append({'lines':[line],'box':line['box'][:],'conf':[line['confidence']]})
            else:
                best['lines'].append(line)
                b=best['box']; best['box']=[min(b[0],x1),min(b[1],y1),max(b[2],x2),max(b[3],y2)]
                best['conf'].append(line['confidence'])
        regions=[]
        for n,g in enumerate(groups):
            g['lines'].sort(key=lambda z:(z['box'][1],z['box'][0]))
            text=' '.join(z['text'] for z in g['lines'])
            x1,y1,x2,y2=g['box']
            regions.append({'id':f'r{n+1}','text_en':text,'text_ar':'','box':[x1,y1,x2,y2],
                            # Keep each detected text line separately so cleanup does not erase the whole speech bubble.
                            'text_boxes':[line['box'][:] for line in g['lines']],
                            'confidence':round(sum(g['conf'])/len(g['conf'])),'font_size':24,'color':'#111111'})
    except Exception as e: raise HTTPException(503,'تعذر تشغيل OCR. حاول بصورة أوضح.')
    m={'image_id':iid,'width':im.width,'height':im.height,'regions':regions}; meta_path(iid).write_text(json.dumps(m,ensure_ascii=False),encoding='utf8')
    return {'image_id':iid,'width':im.width,'height':im.height,'regions':regions,'preview_url':f'/api/image/{iid}/original','message':f'تم رفع الصورة. اكتُشفت {len(regions)} منطقة نصية؛ صحّح النتائج عند الحاجة.'}

@app.post('/api/translate')
def translate(req:TranslateIn):
    iid=safe_id(req.image_id); p=meta_path(iid)
    if not p.exists(): raise HTTPException(404,'الصورة غير موجودة أو انتهت صلاحية ملفاتها؛ ارفع الصفحة مرة أخرى.')
    gemini_key=os.getenv('GEMINI_API_KEY')
    openai_key=os.getenv('OPENAI_API_KEY')
    if not gemini_key and not openai_key:
        raise HTTPException(503,'الترجمة الآلية غير مفعّلة. أضف GEMINI_API_KEY أو OPENAI_API_KEY في إعدادات Render.')
    m=json.loads(p.read_text(encoding='utf8'))
    # Skip empty or very low-confidence OCR to reduce fabricated dialogue from bad OCR.
    lines=[{'id':r['id'],'text':r['text_en']} for r in m['regions']
           if r.get('text_en','').strip() and int(r.get('confidence',0))>=35]
    skipped=sum(1 for r in m['regions'] if r.get('text_en','').strip() and int(r.get('confidence',0))<35)
    if not lines:
        return {'regions':m['regions'],'message':'لم تُكتشف نصوص بثقة كافية للترجمة. صحح النصوص يدويًا أو جرّب صورة أوضح.'}
    prompt=('Translate ONLY the exact English OCR strings below into natural Arabic manga dialogue. '
            'Do not infer context, repair missing words by guessing, add explanations, or invent dialogue. '
            'If a supplied string is gibberish or too incomplete to translate reliably, return an empty string for its id. '
            'Keep each id independent; do not merge different bubbles. Return ONLY a JSON object with exactly the supplied ids. '
            'Style: '+req.style+'\nOCR strings: '+json.dumps(lines,ensure_ascii=False))
    errors=[]
    answer=None
    # Try Gemini first, then fall back to OpenAI if Gemini is overloaded, times out, or rejects the model/key.
    if gemini_key:
        model=os.getenv('GEMINI_MODEL','gemini-2.5-flash').strip()
        try:
            url='https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent?key='+gemini_key
            payload={'contents':[{'parts':[{'text':prompt}]}],
                     'generationConfig':{'responseMimeType':'application/json','temperature':0.0}}
            request=urllib.request.Request(url,data=json.dumps(payload).encode('utf-8'),
                                           headers={'Content-Type':'application/json'},method='POST')
            with urllib.request.urlopen(request,timeout=35) as response:
                result=json.loads(response.read().decode('utf-8'))
            answer_text=result['candidates'][0]['content']['parts'][0]['text']
            answer=json.loads(answer_text)
        except Exception as e:
            status=getattr(e,'code',None) or getattr(e,'status_code',None)
            errors.append('Gemini '+type(e).__name__+(f' HTTP {status}' if status else ''))
            print('Translation provider fallback: '+errors[-1],flush=True)
    if answer is None and openai_key:
        try:
            from openai import OpenAI
            resp=OpenAI(api_key=openai_key,timeout=45,max_retries=1).responses.create(
                model=os.getenv('OPENAI_MODEL','gpt-4.1-mini'),input=prompt)
            answer=json.loads(resp.output_text)
        except Exception as e:
            status=getattr(e,'status_code',None)
            errors.append('OpenAI '+type(e).__name__+(f' HTTP {status}' if status else ''))
            print('Translation provider failure: '+'; '.join(errors),flush=True)
    if answer is None:
        raise HTTPException(502,'تعذرت الترجمة من مزوّدي الخدمة. قد يكون هناك ضغط أو انتهاء الحصة المجانية؛ جرّب مرة أخرى بعد قليل. '+('تفاصيل التشخيص: '+'؛ '.join(errors) if errors else ''))
    expected={item['id'] for item in lines}
    if not isinstance(answer,dict):
        raise HTTPException(502,'رجع محرك الترجمة نتيجة غير مفهومة. حاول مرة أخرى.')
    for r in m['regions']:
        if r['id'] in expected:
            value=answer.get(r['id'],'')
            r['text_ar']=str(value)[:1000] if value is not None else ''
    p.write_text(json.dumps(m,ensure_ascii=False),encoding='utf8')
    msg='اكتملت الترجمة؛ راجع النصوص قبل تركيبها على الصورة.'
    if skipped: msg+=f' تم تجاوز {skipped} منطقة منخفضة الثقة لتقليل التخمين.'
    return {'regions':m['regions'],'message':msg}

@app.post('/api/render')
def render(req:RenderIn):
    iid=safe_id(req.image_id); p=meta_path(iid)
    if not p.exists(): raise HTTPException(404,'الصورة غير موجودة')
    m=json.loads(p.read_text(encoding='utf8')); region=next((r for r in m['regions'] if r['id']==req.region_id),None)
    if not region: raise HTTPException(404,'منطقة النص غير موجودة')
    region['text_ar']=req.text_ar; region['font_size']=req.font_size; region['color']=req.color; p.write_text(json.dumps(m,ensure_ascii=False),encoding='utf8')
    base=cv2.imread(str(DATA/f'{iid}-original.png'))
    if base is None: raise HTTPException(404,'ملف الصورة الأصلي غير موجود')
    mask=np.zeros(base.shape[:2],dtype=np.uint8)
    for r in m['regions']:
        if not r.get('text_ar','').strip(): continue
        # Prefer tight OCR line boxes over the full multi-line region rectangle.
        # This preserves more of the original bubble borders and artwork.
        boxes=r.get('text_boxes') or [r['box']]
        for box in boxes:
            x1,y1,x2,y2=[int(v) for v in box]
            line_h=max(1,y2-y1)
            pad=max(2,min(5,int(line_h*0.08)))
            cv2.rectangle(mask,(max(0,x1-pad),max(0,y1-pad)),
                          (min(base.shape[1]-1,x2+pad),min(base.shape[0]-1,y2+pad)),255,-1)
    clean=cv2.inpaint(base,mask,2,cv2.INPAINT_TELEA) if np.any(mask) else base
    out=Image.fromarray(cv2.cvtColor(clean,cv2.COLOR_BGR2RGB)); draw=ImageDraw.Draw(out)
    fontpath=next((f for f in ['/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'] if os.path.exists(f)),None)
    for r in m['regions']:
        txt=r.get('text_ar','').strip()
        if not txt: continue
        x1,y1,x2,y2=r['box']; w=max(20,x2-x1); h=max(20,y2-y1); size=max(10,min(100,int(r.get('font_size',24))))
        font=ImageFont.truetype(fontpath,size,layout_engine=ImageFont.Layout.RAQM) if fontpath else ImageFont.load_default()
        words=txt.split(); lines=[]; line=''
        for word in words:
            cand=(line+' '+word).strip()
            try: width=draw.textlength(cand,font=font,direction='rtl',language='ar')
            except: width=draw.textlength(cand,font=font)
            if line and width>w-8: lines.append(line); line=word
            else: line=cand
        if line: lines.append(line)
        while lines and len(lines)*size*1.25>h*1.6 and size>10:
            size-=1; font=ImageFont.truetype(fontpath,size,layout_engine=ImageFont.Layout.RAQM) if fontpath else ImageFont.load_default()
        y=y1+(h-len(lines)*size*1.25)/2
        for line in lines:
            try: draw.text((x1+w/2,y),line,font=font,fill=r.get('color','#111111'),anchor='mt',direction='rtl',language='ar')
            except: draw.text((x1+w/2,y),line,font=font,fill=r.get('color','#111111'),anchor='mt')
            y+=size*1.25
    outpath=DATA/f'{iid}-translated.png'; out.save(outpath)
    return {'ok':True,'image_url':f'/api/image/{iid}/translated','note':'راجع الترميم يدويًا؛ قد تتأثر الخلفيات المعقدة.'}

@app.get('/api/image/{image_id}/{kind}')
def get_image(image_id:str,kind:str):
    iid=safe_id(image_id)
    if kind not in ('original','translated'): raise HTTPException(400,'نوع الصورة غير صالح')
    p=DATA/f'{iid}-{kind}.png'
    if not p.exists(): raise HTTPException(404,'الصورة غير موجودة')
    return FileResponse(p,media_type='image/png')
