from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
from sqlalchemy import UniqueConstraint

db = SQLAlchemy()



# === 新增：訂餐揪團群組（OrderGroup）與其常訂餐廳 ===
class OrderGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(12), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<OrderGroup {self.code}>"



# === 新增：聚餐投票群組（VoteGroup）與其票數 ===
class VoteGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(12), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<VoteGroup {self.code}>"









# === 每個「訂餐揪團」群組自己的餐廳 ===
class OrderRestaurant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('order_group.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    hours = db.Column(db.String(120), nullable=True)
    menu_url = db.Column(db.String(300), nullable=True)

    group = db.relationship('OrderGroup', backref='restaurants', lazy=True)

# 訂餐揪團：群組常訂（指向「群組自己的餐廳」）
class OrderFavorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('order_group.id'), nullable=False)
    order_restaurant_id = db.Column(db.Integer, db.ForeignKey('order_restaurant.id'), nullable=False)

    group = db.relationship('OrderGroup', backref='favorites', lazy=True)
    order_restaurant = db.relationship('OrderRestaurant', lazy=True)

    __table_args__ = (UniqueConstraint('group_id', 'order_restaurant_id', name='uq_order_fav'),)

# === 每個「聚餐投票」群組自己的餐廳 ===
class VoteRestaurant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('vote_group.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    hours = db.Column(db.String(120), nullable=True)
    menu_url = db.Column(db.String(300), nullable=True)

    group = db.relationship('VoteGroup', backref='restaurants', lazy=True)

# 聚餐投票：票數（指向「群組自己的餐廳」）
class VoteResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('vote_group.id'), nullable=False)
    vote_restaurant_id = db.Column(db.Integer, db.ForeignKey('vote_restaurant.id'), nullable=False)
    votes = db.Column(db.Integer, default=0, nullable=False)

    group = db.relationship('VoteGroup', backref='results', lazy=True)
    vote_restaurant = db.relationship('VoteRestaurant', lazy=True)

    __table_args__ = (UniqueConstraint('group_id', 'vote_restaurant_id', name='uq_vote_result'),)




# --- 訂餐揪團：群組留言 ---
class OrderComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('order_group.id'), nullable=False)
    nickname = db.Column(db.String(32), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    group = db.relationship('OrderGroup', backref='comments', lazy=True)

# --- 聚餐投票：群組留言 ---
class VoteComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('vote_group.id'), nullable=False)
    nickname = db.Column(db.String(32), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    group = db.relationship('VoteGroup', backref='comments', lazy=True)





# 聚餐投票：群組設定（不改 VoteGroup 結構，避免 migrate）
class VoteGroupMeta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('vote_group.id'), nullable=False, unique=True)
    # 皆以 UTC 存（畫面用你已有的 tw_time 濾鏡轉台北）
    event_at = db.Column(db.DateTime, nullable=False)         # 聚餐日期時間（UTC）
    vote_deadline = db.Column(db.DateTime, nullable=False)    # 投票截止（UTC）
    votes_per_person = db.Column(db.Integer, nullable=False, default=1)  # 1~3

    group = db.relationship('VoteGroup', backref=db.backref('meta', uselist=False), lazy=True)
    __table_args__ = (
        db.Index('ix_vgmeta_group', 'group_id'),
        db.Index('ix_vgmeta_deadline', 'vote_deadline'),
    )

# 聚餐投票：投票憑證（限制：每人同餐廳只能投一次；並統計每人使用票數）
class VoteBallot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('vote_group.id'), nullable=False)
    nickname = db.Column(db.String(10), nullable=False)  # 你已將暱稱限制為 10
    vote_restaurant_id = db.Column(db.Integer, db.ForeignKey('vote_restaurant.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    group = db.relationship('VoteGroup', backref='ballots', lazy=True)
    vote_restaurant = db.relationship('VoteRestaurant', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('group_id', 'nickname', 'vote_restaurant_id', name='uq_ballot_once_per_rest'),
        db.Index('ix_ballot_group_nick', 'group_id', 'nickname'),
    )



# 建立匿名投票憑證表
class VoteToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('vote_group.id'), nullable=False)
    client_id = db.Column(db.String(64), nullable=False)   # 來自 session 的匿名 ID
    vote_restaurant_id = db.Column(db.Integer, db.ForeignKey('vote_restaurant.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        db.UniqueConstraint('group_id', 'client_id', 'vote_restaurant_id', name='uq_token_once_per_rest'),
        db.Index('ix_token_group_client', 'group_id', 'client_id'),
    )
