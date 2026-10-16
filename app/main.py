import os, io, uuid, json
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
    return {'ok':True,'ocr_engine':ocr,'translation_provider':'configured' if os.getenv('OPENAI_API_KEY') else 'manual'}

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
        d=pytesseract.image_to_data(im,lang='eng',output_type=Output.DICT,config='--psm 11')
        groups={}
        for k,word in enumerate(d['text']):
            word=word.strip()
            try: conf=float(d['conf'][k])
            except: conf=-1
            if not word or conf<20: continue
            x,y,w,h=[int(d[a][k]) for a in ('left','top','width','height')]
            key=(d['block_num'][k],d['par_num'][k],d['line_num'][k])
            if key not in groups: groups[key]={'words':[],'box':[x,y,x+w,y+h],'conf':[]}
            g=groups[key]; g['words'].append(word); g['conf'].append(conf); b=g['box']; g['box']=[min(b[0],x),min(b[1],y),max(b[2],x+w),max(b[3],y+h)]
        regions=[]
        for n,g in enumerate(groups.values()):
            x1,y1,x2,y2=g['box']; regions.append({'id':f'r{n+1}','text_en':' '.join(g['words']),'text_ar':'','box':[x1,y1,x2,y2],'confidence':round(sum(g['conf'])/len(g['conf'])),'font_size':24,'color':'#111111'})
    except Exception as e: raise HTTPException(503,'تعذر تشغيل OCR. حاول بصورة أوضح.')
    m={'image_id':iid,'width':im.width,'height':im.height,'regions':regions}; meta_path(iid).write_text(json.dumps(m,ensure_ascii=False),encoding='utf8')
    return {'image_id':iid,'width':im.width,'height':im.height,'regions':regions,'preview_url':f'/api/image/{iid}/original','message':f'تم رفع الصورة. اكتُشفت {len(regions)} منطقة نصية؛ صحّح النتائج عند الحاجة.'}

@app.post('/api/translate')
def translate(req:TranslateIn):
    iid=safe_id(req.image_id); p=meta_path(iid)
    if not p.exists(): raise HTTPException(404,'الصورة غير موجودة')
    key=os.getenv('OPENAI_API_KEY')
    if not key: raise HTTPException(503,'الترجمة الآلية غير مفعّلة. أضف OPENAI_API_KEY في إعدادات الاستضافة أو اكتب الترجمة يدويًا.')
    from openai import OpenAI
    m=json.loads(p.read_text(encoding='utf8')); lines=[{'id':r['id'],'text':r['text_en']} for r in m['regions'] if r['text_en']]
    if not lines: return {'regions':m['regions'],'message':'لم يُكتشف نص لترجمته.'}
    prompt='Translate manga dialogue from English into natural Arabic. Preserve meaning, character tone, short speech-bubble phrasing. Return ONLY a JSON object mapping each id to Arabic text. Style: '+req.style+'\nTexts: '+json.dumps(lines,ensure_ascii=False)
    try:
        resp=OpenAI(api_key=key).responses.create(model=os.getenv('OPENAI_MODEL','gpt-4.1-mini'),input=prompt)
        answer=json.loads(resp.output_text)
        for r in m['regions']:
            if r['id'] in answer: r['text_ar']=str(answer[r['id']])[:1000]
        p.write_text(json.dumps(m,ensure_ascii=False),encoding='utf8')
        return {'regions':m['regions'],'message':'اكتملت الترجمة الآلية؛ راجعها قبل إنشاء الصورة.'}
    except Exception as e:
        # Log only safe diagnostic metadata; never log credentials or request contents.
        print(f"Translation provider error type={type(e).__name__} status={getattr(e, 'status_code', None)}", flush=True)
        raise HTTPException(502,'فشلت الترجمة. راجع سجل الخدمة لتحديد سبب الخطأ.')

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
        x1,y1,x2,y2=r['box']; pad=max(2,int((y2-y1)*.12)); cv2.rectangle(mask,(max(0,x1-pad),max(0,y1-pad)),(min(base.shape[1]-1,x2+pad),min(base.shape[0]-1,y2+pad)),255,-1)
    clean=cv2.inpaint(base,mask,3,cv2.INPAINT_TELEA) if np.any(mask) else base
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
