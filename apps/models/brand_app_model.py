from apps.configs.mysql_config import db

from datetime import datetime

class BrandApp(db.Model):
    __tablename__ = 'brand_apps'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.String(255), nullable=True)
    bundle_id = db.Column(db.String(255), nullable=True)
    note = db.Column(db.String(255), nullable=True)
    status = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=None)
    updated_at = db.Column(db.DateTime, default=None, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime, default=None)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'bundle_id': self.bundle_id,
            'note': self.note,
            'status': self.status,
            'created_at': self.created_at.strftime("%Y-%d-%m %H:%M:%S") if self.created_at else None,
            'updated_at': self.updated_at.strftime("%Y-%d-%m %H:%M:%S") if self.updated_at else None,
            'deleted_at': self.deleted_at.strftime("%Y-%d-%m %H:%M:%S") if self.deleted_at else None
        }
