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
        body { font-family: -apple-system, sans-serif; background: #f5f6f8; color: #1a1a1a; }

        .header { background: #fff; padding: 16px 20px; border-bottom: 1px solid #eee; display: flex; align-items: center; justify-content: space-between; }
        .header h1 { font-size: 17px; font-weight: 700; }
        .header a { font-size: 13px; color: #999; text-decoration: none; }

        .summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; padding: 16px 20px; }
        .card { background: #fff; border-radius: 12px; padding: 14px 10px; text-align: center; }
        .card .count { font-size: 28px; font-weight: 800; }
        .card .label { font-size: 11px; color: #888; margin-top: 3px; }
        .card.blue .count { color: #4488FF; }
        .card.green .count { color: #44AA44; }
        .card.yellow .count { color: #F59E0B; }
        .card.red .count { color: #EF4444; }

        .list { padding: 0 20px 40px; }
        .section-title { font-size: 13px; font-weight: 600; color: #888; margin: 16px 0 8px; text-transform: uppercase; letter-spacing: 0.5px; }

        .review { background: #fff; border-radius: 12px; padding: 14px 16px; margin-bottom: 8px; }
        .review-top { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
        .badge { font-size: 11px; font-weight: 700; padding: 3px 10px; border-radius: 20px; color: #fff; }
        .meta { font-size: 11px; color: #bbb; margin-left: auto; }

        .summary-text { font-size: 15px; font-weight: 600; color: #1a1a1a; line-height: 1.5; }
        .original { margin-top: 8px; }
        .original summary { font-size: 11px; color: #bbb; cursor: pointer; user-select: none; }
        .original-text { font-size: 13px; color: #aaa; line-height: 1.6; margin-top: 6px; }
        .original-text.blurred { filter: blur(4px); cursor: pointer; }
        .original-text.blurred::after { content: '클릭하면 원문을 볼 수 있습니다'; display: block; text-align: center; font-size: 11px; color: #999; filter: blur(0); margin-top: 4px; }

        .empty { text-align: center; padding: 60px 20px; color: #bbb; font-size: 14px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>{{ mall_id }} 리뷰 현황</h1>
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
        <div class="section-title">전체 {{ total }}건</div>
        {% for r in reviews %}
        {% set c = r.classification %}
        <div class="review">
            <div class="review-top">
                <span class="badge" style="background:{{ c.color }}">{{ c.label }}</span>
                <span class="meta">{{ r.get('writer', {}).get('name', '') }} · {{ r.get('created_date', '')[:10] }}</span>
            </div>
            <div class="summary-text">{{ c.get('summary', '') }}</div>
            {% if c.grade == 'red' %}
            <details class="original">
                <summary>원문 보기</summary>
                <div class="original-text blurred">{{ r.get('content', '') }}</div>
            </details>
            {% else %}
            <div class="original-text" style="margin-top:8px">{{ r.get('content', '') }}</div>
            {% endif %}
        </div>
        {% endfor %}
        {% else %}
        <div class="empty">등록된 리뷰가 없습니다</div>
        {% endif %}
    </div>
    <script>
        document.querySelectorAll('.original-text.blurred').forEach(el => {
            el.addEventListener('click', () => el.classList.remove('blurred'));
        });
    </script>
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


@app.route("/preview")
def preview():
    fake = [
        {"content": "배송도 빠르고 제품 퀄리티 너무 좋아요! 재구매 의사 있습니다", "writer": {"name": "김**"}, "created_date": "2026-05-10", "classification": {"grade": "blue", "label": "긍정", "summary": "제품 만족, 재구매 의사", "color": "#4488FF"}},
        {"content": "포장 상태가 불량으로 왔고 제품에 스크래치가 있었습니다. 교환 원합니다", "writer": {"name": "이**"}, "created_date": "2026-05-09", "classification": {"grade": "green", "label": "진짜 불만", "summary": "불량 포장으로 인한 교환 요청", "color": "#44AA44"}},
        {"content": "배송이 너무 늦어요!!! 다신 안 삽니다 진짜 최악이에요", "writer": {"name": "박**"}, "created_date": "2026-05-08", "classification": {"grade": "yellow", "label": "감정적 불만", "summary": "배송 속도 개선 요청", "color": "#F59E0B"}},
        {"content": "이거 사기예요 환불해주세요 고소할겁니다", "writer": {"name": "최**"}, "created_date": "2026-05-07", "classification": {"grade": "red", "label": "악성 의심", "summary": "대응 불필요", "color": "#EF4444"}},
    ]
    counts = {"blue": 1, "green": 1, "yellow": 1, "red": 1}
    return render_template_string(REVIEWS_HTML, mall_id="미리보기", counts=counts, reviews=fake, total=4)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
