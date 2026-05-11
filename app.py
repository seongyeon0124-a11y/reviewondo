import os
from flask import Flask, request, redirect, session, jsonify, render_template_string
from dotenv import load_dotenv
from auth import get_auth_url, get_access_token, get_reviews
from classifier import classify_reviews

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key")


REVIEWS_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>리뷰온도 — {{ mall_id }}</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, sans-serif; background: #f5f5f5; color: #222; }
        .header { background: #fff; padding: 20px 24px; border-bottom: 1px solid #e0e0e0; display: flex; align-items: center; justify-content: space-between; }
        .header h1 { font-size: 18px; font-weight: 700; }
        .header a { font-size: 13px; color: #888; text-decoration: none; }
        .summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; padding: 20px 24px; }
        .card { background: #fff; border-radius: 10px; padding: 16px; text-align: center; border-top: 4px solid; }
        .card .count { font-size: 32px; font-weight: 700; }
        .card .label { font-size: 12px; color: #666; margin-top: 4px; }
        .card.blue { border-color: #4488FF; } .card.blue .count { color: #4488FF; }
        .card.green { border-color: #44AA44; } .card.green .count { color: #44AA44; }
        .card.yellow { border-color: #FFA500; } .card.yellow .count { color: #FFA500; }
        .card.red { border-color: #FF4444; } .card.red .count { color: #FF4444; }
        .list { padding: 0 24px 40px; }
        .list h2 { font-size: 15px; color: #555; margin-bottom: 12px; }
        .review { background: #fff; border-radius: 10px; padding: 16px; margin-bottom: 10px; border-left: 4px solid; }
        .review .badge { display: inline-block; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 20px; color: #fff; margin-bottom: 8px; }
        .review .content { font-size: 14px; line-height: 1.6; color: #333; }
        .review .reason { font-size: 12px; color: #999; margin-top: 6px; }
        .review .meta { font-size: 11px; color: #bbb; margin-top: 4px; }
        .empty { text-align: center; padding: 60px 20px; color: #aaa; }
        .empty p { margin-top: 8px; font-size: 14px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>리뷰온도 — {{ mall_id }}</h1>
        <a href="/">다른 쇼핑몰</a>
    </div>

    <div class="summary">
        <div class="card blue">
            <div class="count">{{ counts.blue }}</div>
            <div class="label">긍정</div>
        </div>
        <div class="card green">
            <div class="count">{{ counts.green }}</div>
            <div class="label">진짜 불만</div>
        </div>
        <div class="card yellow">
            <div class="count">{{ counts.yellow }}</div>
            <div class="label">감정적 불만</div>
        </div>
        <div class="card red">
            <div class="count">{{ counts.red }}</div>
            <div class="label">악성 의심</div>
        </div>
    </div>

    <div class="list">
        {% if reviews %}
            <h2>전체 리뷰 {{ total }}개</h2>
            {% for r in reviews %}
            {% set c = r.classification %}
            <div class="review" style="border-color: {{ c.color }}">
                <span class="badge" style="background: {{ c.color }}">{{ c.label }}</span>
                <div class="content">{{ r.get('content', '') }}</div>
                {% if c.reason %}
                <div class="reason">{{ c.reason }}</div>
                {% endif %}
                <div class="meta">{{ r.get('writer', {}).get('name', '') }} · {{ r.get('created_date', '')[:10] }}</div>
            </div>
            {% endfor %}
        {% else %}
            <div class="empty">
                <div style="font-size: 48px;">📭</div>
                <p>등록된 리뷰가 없습니다</p>
            </div>
        {% endif %}
    </div>
</body>
</html>
"""

MAIN_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>리뷰온도</title>
    <style>
        body { font-family: sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }
        input { width: 100%; padding: 10px; margin: 10px 0; font-size: 16px; }
        button { width: 100%; padding: 12px; background: #4488FF; color: white;
                 border: none; font-size: 16px; cursor: pointer; border-radius: 6px; }
        button:hover { background: #2266DD; }
    </style>
</head>
<body>
    <h2>리뷰온도</h2>
    <p>카페24 쇼핑몰 아이디를 입력하세요</p>
    <form action="/login" method="get">
        <input name="mall_id" placeholder="예: myshop (myshop.cafe24.com에서 myshop 부분)" required>
        <button type="submit">연결하기</button>
    </form>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(MAIN_HTML)


@app.route("/login")
def login():
    mall_id = request.args.get("mall_id", "").strip()
    if not mall_id:
        return redirect("/")
    session["mall_id"] = mall_id
    return redirect(get_auth_url(mall_id))


@app.route("/callback")
def callback():
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        return f"오류: {error} — {request.args.get('error_description', '')}", 400

    if not code:
        return "code 없음", 400

    mall_id = session.get("mall_id")
    if not mall_id:
        return "세션 만료. 다시 시도해주세요.", 400

    token_data = get_access_token(mall_id, code)
    if "access_token" not in token_data:
        return f"토큰 발급 실패: {token_data}", 400

    session["access_token"] = token_data["access_token"]
    return redirect("/reviews")


@app.route("/reviews")
def reviews():
    mall_id = session.get("mall_id")
    access_token = session.get("access_token")

    if not mall_id or not access_token:
        return redirect("/")

    data = get_reviews(mall_id, access_token)

    if "error" in data and "articles" not in data:
        return jsonify({"오류": data.get("error", "알 수 없는 오류")}), 400

    if data.get("error"):
        return jsonify({"오류": data["error"]}), 400

    # 401: 토큰 만료
    if data.get("code") == 401 or data.get("error", {}).get("code") == 401 if isinstance(data.get("error"), dict) else False:
        session.clear()
        return redirect("/")

    raw_reviews = data.get("articles", [])
    classified, counts = classify_reviews(raw_reviews)

    return render_template_string(REVIEWS_HTML,
        mall_id=mall_id,
        counts=counts,
        reviews=classified,
        total=len(raw_reviews)
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
