from flask import Flask, render_template, request, redirect, url_for, flash , session
from models import (
    db, # Meal, Restaurant暫時刪除
    OrderGroup,VoteGroup,# 兩種群組
    OrderRestaurant, OrderFavorite, # 訂餐用
    VoteRestaurant, VoteResult,   # 投票用
    OrderComment, VoteComment, # 留言
    VoteGroupMeta,VoteBallot ,VoteToken)  # 聚餐投票 - 群組設定.投票規則
from datetime import datetime,timezone, timedelta
import os
import random
import uuid



def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "devkey")
    db_url = os.environ.get("DATABASE_URL", "sqlite:///app.db")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1) 
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True} # 避免閒置連線失效

    db.init_app(app)

    MAX_RESTAURANTS = 10
    MIN_RESTAURANTS = 1
    TAIPEI = timezone(timedelta(hours=8))

    with app.app_context():
        db.create_all()



    # 產生代碼（僅英數，避開易混淆字元）
    def _gen_code(n=6):
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 不含易混淆字元
        return "".join(random.choice(alphabet) for _ in range(n))

    # 依代碼找「訂餐揪團」群組；無或不存在 → 回 None
    def get_order_group(code: str | None):
        if not code:
            return None
        return OrderGroup.query.filter(db.func.lower(OrderGroup.code) == (code or "").lower()).first()

    # 依代碼找「聚餐投票」群組；無或不存在 → 回 None
    def get_vote_group(code: str | None):
        if not code:
            return None
        return VoteGroup.query.filter(db.func.lower(VoteGroup.code) == (code or "").lower()).first()
    
    # 暱稱：每位使用者在每個群組（與 scope）獨立設定，存於 session
    def _nick_key(scope: str, code: str) -> str:
        return f"{scope}:{(code or '').upper()}"

    def get_nick(scope: str, code: str) -> str | None:
        nicks = session.get("nicks") or {}
        return nicks.get(_nick_key(scope, code))

    def set_nick(scope: str, code: str, nickname: str):
        nickname = (nickname or "").strip()[:10] or "訪客"
        nicks = session.get("nicks") or {}
        nicks[_nick_key(scope, code)] = nickname
        session["nicks"] = nicks

    def tw_time(dt):
        """將資料庫時間（假設為 UTC 或 naive 視為 UTC）顯示成台北時間 YYYY-MM-DD HH:MM。"""
        if dt is None:
            return ""
        if getattr(dt, "tzinfo", None) is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M")
    app.jinja_env.filters["tw_time"] = tw_time

    def to_aware_utc(dt):
        """把資料庫取回的 datetime 正常化成 aware UTC：naive -> 加上 UTC；aware -> 轉成 UTC。"""
        if dt is None:
            return None
        if getattr(dt, "tzinfo", None) is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def trim_comments(model, group_id: int, keep: int = 50):
        """保留最新 keep 筆，刪掉更舊的（以 created_at 由新到舊排序）。"""
        # 取出超出 keep 的那些 id（由新到舊 offset keep）
        stale = (model.query
                 .filter_by(group_id=group_id)
                 .order_by(model.created_at.desc())
                 .offset(keep)
                 .with_entities(model.id)
                 .all())
        if stale:
            ids = [sid for (sid,) in stale]
            model.query.filter(model.id.in_(ids)).delete(synchronize_session=False)
            db.session.commit()

    def parse_local_to_utc(dt_local_str: str) -> datetime:
        """將 <input type=datetime-local> 傳回的 'YYYY-MM-DDTHH:MM' 視為台北時間，再轉 UTC。"""
        # 防空值
        if not dt_local_str:
            return None
        # 只取到分鐘
        dt_naive = datetime.strptime(dt_local_str, "%Y-%m-%dT%H:%M")
        dt_local = dt_naive.replace(tzinfo=TAIPEI)
        return dt_local.astimezone(timezone.utc)

    def cleanup_expired_vote_group(group: "VoteGroup"):
        if not group or not group.meta:
            return
        # 先把 event_at 轉成 aware UTC
        event_at_utc = to_aware_utc(group.meta.event_at)
        # 轉台北，再取當天 23:59
        event_local = event_at_utc.astimezone(TAIPEI)
        event_end_local = event_local.replace(hour=23, minute=59, second=0, microsecond=0)
        event_end_utc = event_end_local.astimezone(timezone.utc)

        if datetime.now(timezone.utc) >= event_end_utc:
            # 刪關聯
            VoteBallot.query.filter_by(group_id=group.id).delete(synchronize_session=False)
            VoteResult.query.filter_by(group_id=group.id).delete(synchronize_session=False)
            VoteRestaurant.query.filter_by(group_id=group.id).delete(synchronize_session=False)
            VoteGroupMeta.query.filter_by(group_id=group.id).delete(synchronize_session=False)
            db.session.delete(group)
            db.session.commit()

    def get_client_id() -> str:
        cid = session.get("cid")
        if not cid:
            cid = uuid.uuid4().hex  # 32字元
            session["cid"] = cid
        return cid
    








    @app.route("/", methods=["GET"])
    def home():
        return render_template("home.html")

    @app.route("/order", methods=["GET"])
    def order():
        code = request.args.get("code")
        group = get_order_group(code)

        if not group:
            return render_template(
                "order.html",
                group=None, restaurants=[], fav_ids=set(),
                scope="order", saved_nick=None,
                comments_stream_url=None, comment_post_url=None
            )

        restaurants = OrderRestaurant.query.filter_by(group_id=group.id).order_by(OrderRestaurant.name.asc()).all()
        fav_ids = {f.order_restaurant_id for f in OrderFavorite.query.filter_by(group_id=group.id).all()}

        return render_template(
            "order.html",
            group=group, restaurants=restaurants, fav_ids=fav_ids,
            scope="order",
            saved_nick=get_nick("order", group.code),
            comments_stream_url=url_for("og_comments_stream", code=group.code),
            comment_post_url=url_for("og_post_comment", code=group.code)
        )

    # 訂餐揪團：留言串流（右側自動刷新抓這個部分 HTML）
    @app.route("/og/<code>/comments/stream", methods=["GET"])
    def og_comments_stream(code):
        group = OrderGroup.query.filter_by(code=code).first_or_404()
        comments = (OrderComment.query
                    .filter_by(group_id=group.id)
                    .order_by(OrderComment.created_at.asc())
                    .limit(50).all())
        return render_template("partials/comments_stream.html", comments=comments)

    # 訂餐揪團：新增留言（同時可更新暱稱）
    @app.route("/og/<code>/comments", methods=["POST"])
    def og_post_comment(code):
        group = OrderGroup.query.filter_by(code=code).first_or_404()
        nickname = (request.form.get("nickname") or "").strip()
        message = (request.form.get("message") or "").strip()

        if nickname:
            set_nick("order", code, nickname)
        nickname = (get_nick("order", code) or "訪客")[:10]   # ← 最多 10

        if not message:
            flash("請輸入留言內容。", "error")
            return redirect(url_for("order", code=code))
        
        message = message[:30]  # ← 最多 30

        db.session.add(OrderComment(group_id=group.id, nickname=nickname, message=message))
        db.session.commit()
        trim_comments(OrderComment, group.id, keep=50)
        return redirect(url_for("order", code=code))


    @app.route("/og/<code>/restaurants/new", methods=["GET", "POST"])
    def og_add_restaurant(code):
        group = OrderGroup.query.filter_by(code=code).first_or_404()

        if request.method == "POST":
            name = (request.form.get("name") or "").strip()
            phone = (request.form.get("phone") or "").strip()
            hours = (request.form.get("hours") or "").strip()
            menu_url = (request.form.get("menu_url") or "").strip()

            count = OrderRestaurant.query.filter_by(group_id=group.id).count()
            if count >= MAX_RESTAURANTS:
                flash(f"此群組餐廳已達上限 {MAX_RESTAURANTS} 家。", "error")
                return redirect(url_for("order", code=group.code))

            if not name:
                flash("請輸入餐廳名稱。", "error")
                return redirect(url_for("og_add_restaurant", code=group.code))

            exists = OrderRestaurant.query.filter(
                OrderRestaurant.group_id == group.id,
                db.func.lower(OrderRestaurant.name) == name.lower()
            ).first()
            if exists:
                flash("此餐廳已存在於本群組。", "warning")
                return redirect(url_for("order", code=group.code))

            db.session.add(OrderRestaurant(group_id=group.id, name=name, phone=phone, hours=hours, menu_url=menu_url))
            db.session.commit()
            flash("新增餐廳成功！", "success")
            return redirect(url_for("order", code=group.code))

        return render_template("og_add_restaurant.html", group=group)

    @app.route("/og/<code>/restaurants/manage", methods=["GET"])
    def og_manage_restaurants(code):
        group = OrderGroup.query.filter_by(code=code).first_or_404()
        restaurants = OrderRestaurant.query.filter_by(group_id=group.id).order_by(OrderRestaurant.name.asc()).all()
        too_few = len(restaurants) <= MIN_RESTAURANTS
        return render_template("og_manage_restaurants.html", group=group, restaurants=restaurants, too_few=too_few)

    @app.route("/og/<code>/restaurants/<int:order_restaurant_id>/delete", methods=["POST"])
    def og_delete_restaurant(code, order_restaurant_id):
        group = OrderGroup.query.filter_by(code=code).first_or_404()
        q = OrderRestaurant.query.filter_by(group_id=group.id)
        if q.count() <= MIN_RESTAURANTS:
            flash(f"至少需保留 {MIN_RESTAURANTS} 家餐廳，無法刪除。", "error")
            return redirect(url_for("og_manage_restaurants", code=group.code))

        r = q.filter_by(id=order_restaurant_id).first_or_404()
        # 同步清掉常訂關聯
        OrderFavorite.query.filter_by(group_id=group.id, order_restaurant_id=r.id).delete()
        db.session.delete(r)
        db.session.commit()
        flash("已刪除餐廳。", "info")
        return redirect(url_for("og_manage_restaurants", code=group.code))


    
    @app.route("/og/<code>/favorite/<int:order_restaurant_id>/toggle", methods=["POST"])
    def toggle_favorite_order(code, order_restaurant_id):
        group = OrderGroup.query.filter_by(code=code).first_or_404()
        r = OrderRestaurant.query.filter_by(group_id=group.id, id=order_restaurant_id).first_or_404()

        link = OrderFavorite.query.filter_by(group_id=group.id, order_restaurant_id=r.id).first()
        if link:
            db.session.delete(link)
            db.session.commit()
            flash("已從常訂移除。", "info")
        else:
            db.session.add(OrderFavorite(group_id=group.id, order_restaurant_id=r.id))
            db.session.commit()
            flash("已加入常訂餐廳！", "success")

        return redirect(url_for("order", code=group.code))


    @app.route("/vote", methods=["GET"])
    def vote():
        code = request.args.get("code")
        group = get_vote_group(code)

        if not group:
            return render_template("vote.html",
                group=None, restaurants=[], votes={},
                scope="vote", saved_nick=None,
                comments_stream_url=None, comment_post_url=None
            )

        cleanup_expired_vote_group(group)
        group = get_vote_group(code)
        if not group:
            flash("此群組已過期並刪除。", "info")
            return redirect(url_for("vote"))

        meta = VoteGroupMeta.query.filter_by(group_id=group.id).first()
        restaurants = VoteRestaurant.query.filter_by(group_id=group.id).order_by(VoteRestaurant.name.asc()).all()
        votes_map = {vr.vote_restaurant_id: vr.votes for vr in VoteResult.query.filter_by(group_id=group.id)}

        now_utc = datetime.now(timezone.utc)
        deadline_utc = to_aware_utc(meta.vote_deadline) if meta else None
        is_closed = bool(meta and deadline_utc and now_utc >= deadline_utc)

        winner_ids = set()
        if is_closed and votes_map:
            max_votes = max(votes_map.values())
            if max_votes > 0:
                winner_ids = {rid for rid, v in votes_map.items() if v == max_votes}

        return render_template(
            "vote.html",
            group=group, restaurants=restaurants, votes=votes_map,
            scope="vote",
            saved_nick=get_nick("vote", group.code),
            comments_stream_url=url_for("vg_comments_stream", code=group.code),
            comment_post_url=url_for("vg_post_comment", code=group.code),
            meta=meta, is_closed=is_closed, winner_ids=winner_ids
        )

    
    # 聚餐投票：留言串流
    @app.route("/vg/<code>/comments/stream", methods=["GET"])
    def vg_comments_stream(code):
        group = VoteGroup.query.filter_by(code=code).first_or_404()
        comments = (VoteComment.query
                    .filter_by(group_id=group.id)
                    .order_by(VoteComment.created_at.asc())
                    .limit(50).all())
        return render_template("partials/comments_stream.html", comments=comments)

    # 聚餐投票：新增留言
    @app.route("/vg/<code>/comments", methods=["POST"])
    def vg_post_comment(code):
        group = VoteGroup.query.filter_by(code=code).first_or_404()
        nickname = (request.form.get("nickname") or "").strip()
        message = (request.form.get("message") or "").strip()

        if nickname:
            set_nick("vote", code, nickname)
        nickname = (get_nick("vote", code) or "訪客")[:10]

        if not message:
            flash("請輸入留言內容。", "error")
            return redirect(url_for("vote", code=code))
        
        message = message[:30]
        db.session.add(VoteComment(group_id=group.id, nickname=nickname, message=message))
        db.session.commit()
        trim_comments(VoteComment, group.id, keep=50)
        return redirect(url_for("vote", code=code))


    
    @app.route("/vg/<code>/restaurants/new", methods=["GET", "POST"])
    def vg_add_restaurant(code):
        group = VoteGroup.query.filter_by(code=code).first_or_404()

        if request.method == "POST":
            name = (request.form.get("name") or "").strip()
            phone = (request.form.get("phone") or "").strip()
            hours = (request.form.get("hours") or "").strip()
            menu_url = (request.form.get("menu_url") or "").strip()

            count = VoteRestaurant.query.filter_by(group_id=group.id).count()
            if count >= MAX_RESTAURANTS:
                flash(f"此群組餐廳已達上限 {MAX_RESTAURANTS} 家。", "error")
                return redirect(url_for("vote", code=group.code))

            if not name:
                flash("請輸入餐廳名稱。", "error")
                return redirect(url_for("vg_add_restaurant", code=group.code))

            exists = VoteRestaurant.query.filter(
                VoteRestaurant.group_id == group.id,
                db.func.lower(VoteRestaurant.name) == name.lower()
            ).first()
            if exists:
                flash("此餐廳已存在於本群組。", "warning")
                return redirect(url_for("vote", code=group.code))

            db.session.add(VoteRestaurant(group_id=group.id, name=name, phone=phone, hours=hours, menu_url=menu_url))
            db.session.commit()
            flash("新增餐廳成功！", "success")
            return redirect(url_for("vote", code=group.code))

        return render_template("vg_add_restaurant.html", group=group)

    @app.route("/vg/<code>/restaurants/manage", methods=["GET"])
    def vg_manage_restaurants(code):
        group = VoteGroup.query.filter_by(code=code).first_or_404()
        restaurants = VoteRestaurant.query.filter_by(group_id=group.id).order_by(VoteRestaurant.name.asc()).all()
        too_few = len(restaurants) <= MIN_RESTAURANTS
        return render_template("vg_manage_restaurants.html", group=group, restaurants=restaurants, too_few=too_few)

    @app.route("/vg/<code>/restaurants/<int:vote_restaurant_id>/delete", methods=["POST"])
    def vg_delete_restaurant(code, vote_restaurant_id):
        group = VoteGroup.query.filter_by(code=code).first_or_404()
        q = VoteRestaurant.query.filter_by(group_id=group.id)
        if q.count() <= MIN_RESTAURANTS:
            flash(f"至少需保留 {MIN_RESTAURANTS} 家餐廳，無法刪除。", "error")
            return redirect(url_for("vg_manage_restaurants", code=group.code))

        r = q.filter_by(id=vote_restaurant_id).first_or_404()
        # 同步清掉票數
        VoteResult.query.filter_by(group_id=group.id, vote_restaurant_id=r.id).delete()
        db.session.delete(r)
        db.session.commit()
        flash("已刪除餐廳。", "info")
        return redirect(url_for("vg_manage_restaurants", code=group.code))

    @app.route("/vg/<code>/vote/<int:vote_restaurant_id>", methods=["POST"])
    def vote_restaurant(code, vote_restaurant_id):
        group = VoteGroup.query.filter_by(code=code).first_or_404()
        r = VoteRestaurant.query.filter_by(group_id=group.id, id=vote_restaurant_id).first_or_404()
        meta = VoteGroupMeta.query.filter_by(group_id=group.id).first()

        # 截止檢查（使用你前面寫好的 to_aware_utc）
        deadline_utc = to_aware_utc(meta.vote_deadline) if meta else None
        if deadline_utc and datetime.now(timezone.utc) >= deadline_utc:
            flash("投票已截止。", "info")
            return redirect(url_for("vote", code=code))

        # 取得匿名身份（每個瀏覽器一組）
        client_id = get_client_id()

        # 同餐廳僅能一次（以 client_id 判定）
        existed = VoteToken.query.filter_by(group_id=group.id, client_id=client_id,
                                            vote_restaurant_id=r.id).first()
        if existed:
            flash("你已經投過這家餐廳囉！", "warning")
            return redirect(url_for("vote", code=code))

        # 每人（每 client_id）投票上限
        limit = meta.votes_per_person if meta else 1
        used = VoteToken.query.filter_by(group_id=group.id, client_id=client_id).count()
        if used >= limit:
            flash(f"每人限投 {limit} 票，你已用完。", "warning")
            return redirect(url_for("vote", code=code))

        # 記錄 Token（身份限制）
        db.session.add(VoteToken(group_id=group.id, client_id=client_id, vote_restaurant_id=r.id))

        # 記錄 Ballot（提供顯示用途；暱稱可選）
        nickname = (get_nick("vote", code) or "訪客")[:10]
        db.session.add(VoteBallot(group_id=group.id, nickname=nickname, vote_restaurant_id=r.id))

        # 統計 +1
        vr = VoteResult.query.filter_by(group_id=group.id, vote_restaurant_id=r.id).first()
        if not vr:
            vr = VoteResult(group_id=group.id, vote_restaurant_id=r.id, votes=0)
            db.session.add(vr)
        vr.votes += 1

        db.session.commit()
        flash("已投票！", "success")
        return redirect(url_for("vote", code=code))
    

    @app.route("/group/new", methods=["GET", "POST"])
    def group_new():
        scope = request.args.get("scope", "vote")
        # 若沒帶 next，預設與 scope 相同（'order' → order、'vote' → vote）
        next_page = request.args.get("next") or scope

        if request.method == "POST":
            name = (request.form.get("name") or "").strip()

            if scope == "order":
                # 建立「訂餐揪團」群組
                code = _gen_code(6)
                og = OrderGroup(code=code, name=name)
                db.session.add(og)
                db.session.commit()
                flash("已建立訂餐群組！", "success")
                return redirect(url_for(next_page, code=og.code))  # ← 立刻 return

            elif scope == "vote":
                # 建立「聚餐投票」群組（含 meta）
                event_at_local = request.form.get("event_at")
                deadline_local = request.form.get("vote_deadline")
                votes_per_person = int(request.form.get("votes_per_person") or 1)

                event_at_utc = parse_local_to_utc(event_at_local)
                deadline_utc = parse_local_to_utc(deadline_local)
                now_utc = datetime.now(timezone.utc)

                # 驗證（整點/時間關係）
                if not event_at_utc or not deadline_utc:
                    flash("請填寫『聚餐日期時間』與『投票截止時間』。", "error")
                    return redirect(url_for("group_new", scope="vote", next_page=next_page))
                if event_at_utc.minute != 0 or deadline_utc.minute != 0:
                    flash("時間必須為整點（分鐘為 00）。", "error")
                    return redirect(url_for("group_new", scope="vote", next_page=next_page))
                if not (deadline_utc < event_at_utc):
                    flash("聚餐時間必須晚於投票截止時間。", "error")
                    return redirect(url_for("group_new", scope="vote", next_page=next_page))
                if event_at_utc <= now_utc:
                    flash("聚餐時間必須晚於目前時間。", "error")
                    return redirect(url_for("group_new", scope="vote", next_page=next_page))
                if votes_per_person not in (1, 2, 3):
                    votes_per_person = 1

                code = _gen_code(6)
                vg = VoteGroup(code=code, name=name)
                db.session.add(vg)
                db.session.flush()
                db.session.add(VoteGroupMeta(
                    group_id=vg.id,
                    event_at=event_at_utc,
                    vote_deadline=deadline_utc,
                    votes_per_person=votes_per_person
                ))
                db.session.commit()
                flash("已建立聚餐投票群組！", "success")
                return redirect(url_for(next_page, code=vg.code))  # ← 立刻 return

            else:
                flash("未知的群組類型。", "error")
                return redirect(url_for("index"))  # 依你首頁路由調整

        # GET：顯示不同表單
        if scope == "vote":
            return render_template("group_new_vote.html", scope="vote", next_page=next_page)
        else:
            return render_template("group_new_order.html", scope="order", next_page=next_page)
        

    @app.route("/group/join", methods=["GET", "POST"])
    def group_join():
        scope = request.args.get("scope", "vote")
        next_page = request.args.get("next_page", "vote")
        if request.method == "POST":
            code = (request.form.get("code") or "").strip().upper()
            if scope == "order":
                g = OrderGroup.query.filter(db.func.upper(OrderGroup.code) == code).first()
            else:
                g = VoteGroup.query.filter(db.func.upper(VoteGroup.code) == code).first()

            if not g:
                flash("找不到該群組代碼。", "error")
                return redirect(url_for("group_join", scope=scope, next_page=next_page))
            flash("加入群組成功！", "success")
            return redirect(url_for(next_page, code=g.code))
        return render_template("group_join.html", scope=scope, next_page=next_page)
    

    @app.route("/healthz") # for 佈署用
    def healthz():
        return "ok", 200
    
    return app




if __name__ == "__main__":
    # Running via `python app.py`
    app = create_app()
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

