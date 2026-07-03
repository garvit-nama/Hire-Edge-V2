import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    subscription_tier = db.Column(db.String(50), default='free') # 'free' or 'premium'
    free_analyses_used = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    # Relationships
    jobs = db.relationship('Job', backref='user', lazy=True)

class Job(db.Model):
    id = db.Column(db.String(36), primary_key=True) # Storing UUIDs
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    job_role = db.Column(db.String(255))
    model = db.Column(db.String(100))
    status = db.Column(db.String(50), default='queued') # queued, complete, error
    progress = db.Column(db.Integer, default=0)
    current_message = db.Column(db.String(255), default='Queued')
    report_content = db.Column(db.Text, nullable=True) # The generated text report
    results_json = db.Column(db.String, nullable=True) # Stored JSON of individual agent outputs
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    # Freemium tier tracking (Phase 3)
    analysis_number = db.Column(db.Integer, default=1) # 1st, 2nd, 3rd... analysis for this user
    user_tier_at_time = db.Column(db.String(50), default='free') # Snapshot of tier when analysis ran
    is_truncated = db.Column(db.Boolean, default=False) # Whether content was truncated for free users
