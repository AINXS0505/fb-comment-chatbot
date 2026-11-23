# 🤖 Meta Facebook Comment AI Auto-Reply Bot & CRM Dashboard

Энэхүү систем нь Facebook хуудасны постын комментуудад **Google Gemini AI** ашиглан хүний сэтгэл хөдлөл, асуултын утгыг (Sentiment & Intent) шинжилж, **байгалийн найрсаг монгол хэлээр нийтийн хариу үлдээх** болон **хэрэглэгчийн Messenger чат руу хувийн зурвас (Private Reply)** автоматаар илгээдэг бие даасан систем юм.

Мөн коммент доторх **8 оронтой Монгол утасны дугаарыг** автоматаар таньж, захиалгын системд (CRM Lead) бүртгэх боломжтой Admin Dashboard-тай.

---

## ✨ Үндсэн боломжууд

1. **Google Gemini AI холболт**: Хэрэглэгчийн комментыг шинжлээд (эерэг, сөрөг, үнэ асуусан, хүргэлт сонирхсон, захиалга) байгалийн найрсаг хариу үүсгэнэ.
2. **Facebook Private Reply**: Хэрэглэгчийн хувийн Messenger чат руу дэлгэрэнгүй үнийн санал, мэдээллийг шууд илгээнэ.
3. **Утасны дугаар таних (Lead Capture)**: Комментоос Монгол утасны дугаарыг илрүүлж CRM самбарт бүртгэнэ (CSV-ээр татах боломжтой).
4. **Пост тус бүрийн хариулах дүрэм**: Аль постод ямар түлхүүр үгээр хариулахыг вэб интерфэйсээр тохируулна.
5. **AI Тест Симулятор**: Facebook-ээс коммент ирэхийг хүлээлгүй Dashboard дээрээ шууд коммент туршиж AI хариуг шалгана.
6. **Vercel & GitHub Ready**: Vercel дээр шууд байрших (Deploy) тохиргоо бүрэн хийгдсэн.

---

## 🚀 1. Локал орчинд ажиллуулах (Local Dev)

### Шаардлага:
- Python 3.10+
- Git

### Ажиллуулах:
```bash
# 1. Төслийн хавтас руу орох
cd fb-comment-chatbot

# 2. Сангуудыг суулгах
pip install -r requirements.txt

# 3. Серверийг асаах
python -m uvicorn api.index:app --reload --port 8000
```

Хөтөч дээрээ **`http://localhost:8000`** хаягаар орж Admin Dashboard-аа харна уу.

---

## 🌐 2. Vercel дээр байршуулах (Deploy to Vercel)

Энэ төсөл нь Vercel-ийн Python Serverless Architecture-д бүрэн тохирсон `vercel.json` тохиргоотой.

### Алхам 1: GitHub-д байршуулах
```bash
git init
git add .
git commit -m "Initial commit: Facebook AI Comment Bot"
git branch -M main
git remote add origin https://github.com/<таны-хэрэглэгчийн-нэр>/<таны-репо-нэр>.git
git push -u origin main
```

### Алхам 2: Vercel-д холбох
1. [vercel.com](https://vercel.com) руу өөрийн GitHub эрхээр нэвтэрнэ.
2. **Add New...** -> **Project** сонгоно.
3. Өөрийн GitHub репог сонгоод **Import** дарна.
4. **Environment Variables** хэсэгт дараах хувьсагчдыг нэмнэ:
   - `GEMINI_API_KEY`: Таны Google Gemini API түлхүүр
   - `PAGE_ACCESS_TOKEN`: Таны Facebook Page Access Token
   - `VERIFY_TOKEN`: Таны зохиосон нууц үг (Жишээ нь: `my_meta_secret_2026`)
   - `APP_SECRET`: Meta Developer App Secret
5. **Deploy** товчийг дарна. 
6. Байршсаны дараа Vercel танд `https://таны-апп.vercel.app` гэсэн үнэгүй найдвартай SSL холболттой домэйн өгнө.

---

## 🔑 3. Meta for Developers (Facebook) холбох заавар

### Алхам 1: App үүсгэх
1. [Meta for Developers](https://developers.facebook.com) руу орж **My Apps -> Create App** дарна.
2. Төрөл дээр нь **Other** -> **Business** сонгоно.
3. **App Settings -> Basic** хэсгээс **App Secret**-ээ хуулж авна.

### Алхам 2: Page Access Token авах
1. **Graph API Explorer** руу орно.
2. **User or Page** дээрээс өөрийн хуудсаа сонгоно.
3. Дараах зөвшөөрлүүдийг (Permissions) нэмнэ:
   - `pages_read_engagement`
   - `pages_manage_posts`
   - `pages_manage_metadata`
   - `pages_messaging`
4. **Generate Access Token** дарж хуулж авна.

### Алхам 3: Webhook холбох
1. Meta Developer Console -> зүүн цэснээс **Webhooks** сонгоно.
2. Объектоор нь **Page** сонгоод **Subscribe to this object** дарна.
3. **Callback URL**: `https://таны-апп.vercel.app/api/webhook`
4. **Verify Token**: Таны тохируулсан `VERIFY_TOKEN`
5. **Verify and Save** дарж холбоно.
6. Холбогдсоны дараа **`feed`** болон **`messages`** талбаруудыг **Subscribe** хийнэ.

---

## 💡 4. Google Gemini API Key авах (Үнэгүй)

1. [Google AI Studio](https://aistudio.google.com/) руу Google хаягаараа нэвтэрнэ.
2. **Get API Key** -> **Create API Key** дарна.
3. Гарч ирсэн түлхүүрийг Dashboard-ийн **Систем & AI Тохиргоо** цэсэнд оруулж хадгална.

---

## 📁 Төслийн бүтэц

```
fb-comment-chatbot/
├── api/
│   ├── index.py             # FastAPI үндсэн сервер & Webhook route-үүд
│   ├── ai_service.py        # Gemini AI шинжилгээ, Intent/Sentiment, Утасны дугаар шүүлт
│   ├── facebook_service.py  # Meta Graph API, Signature verification, Private Reply
│   └── database.py          # SQLite / CRM өгөгдлийн сангийн логик
├── templates/
│   └── index.html           # Tailwind CSS дээр суурилсан Admin Dashboard
├── static/                  # Статик файлууд
├── vercel.json              # Vercel Serverless байршуулалтын тохиргоо
├── requirements.txt         # Шаардлагатай Python сангууд
├── .env.example             # Жишээ орчны хувьсагчид
└── README.md                # Дэлгэрэнгүй гарын авлага
```
