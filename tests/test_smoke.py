from fastapi.testclient import TestClient
from app.main import app
from PIL import Image, ImageDraw
import io
client=TestClient(app)
def test_health():
    r=client.get('/api/health'); assert r.status_code==200 and r.json()['ok']
def test_upload_and_render():
    im=Image.new('RGB',(640,360),'white'); d=ImageDraw.Draw(im); d.text((100,100),'HELLO WORLD!',fill='black')
    b=io.BytesIO(); im.save(b,format='PNG'); b.seek(0)
    r=client.post('/api/upload',files={'file':('test.png',b.getvalue(),'image/png')}); assert r.status_code==200
    data=r.json(); assert data['width']==640 and 'image_id' in data
    if data['regions']:
        rr=client.post('/api/render',json={'image_id':data['image_id'],'region_id':data['regions'][0]['id'],'text_ar':'مرحبا','font_size':22,'color':'#111111'})
        assert rr.status_code==200
        assert client.get(data['preview_url']).status_code==200
        assert client.get(rr.json()['image_url']).status_code==200
def test_reject_wrong_type():
    r=client.post('/api/upload',files={'file':('x.txt',b'hello','text/plain')}); assert r.status_code==415
def test_translate_requires_server_key_or_clear_error(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    r=client.post('/api/translate',json={'image_id':'a'*32})
    assert r.status_code==404 or (r.status_code==503 and 'OPENAI_API_KEY' in r.json()['detail'])
def test_reject_invalid_image_id():
    r=client.post('/api/render',json={'image_id':'../../etc/passwd','region_id':'r1','text_ar':'اختبار'})
    assert r.status_code==400
