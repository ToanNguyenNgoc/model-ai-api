from sqlalchemy import Column, String, Integer, BigInteger, Date, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from apps.configs.mysql_config import db

class UserModel(db.Model):
    __tablename__ = 'users'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    fullname = Column(String(255))
    email = Column(String(255), unique=True)
    telephone = Column(String(255))
    birthday = Column(Date)
    gender = Column(Integer)
    email_verified_at = Column(DateTime)
    password = Column(String(255))
    remember_token = Column(String(100))
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime)
    platform = Column(String(255))
    is_active = Column(Boolean, default=1)
    user_organization_id = Column(Integer)

    def to_dict(self):
        return {
            "id": self.id,
            "fullname": self.fullname,
            "email": self.email,
            "telephone": self.telephone,
            "birthday": self.birthday.strftime('%Y-%m-%d') if self.birthday else None,
            "gender": self.gender,
            "email_verified_at": self.email_verified_at.isoformat() if self.email_verified_at else None,
            "platform": self.platform,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
