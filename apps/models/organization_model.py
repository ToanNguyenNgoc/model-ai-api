from apps.configs.mysql_config import db

class OrganizationModel(db.Model):
  __tablename__ = 'organizations'

  id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
  name = db.Column(db.String(255), nullable=True)
  subdomain = db.Column(db.String)
  domain = db.Column(db.String)
  db_name = db.Column(db.String)
  latitude = db.Column(db.String)
  longitude = db.Column(db.String)
  address = db.Column(db.String)

  def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'subdomain': self.subdomain,
            'domain': self.domain,
            'db_name': self.db_name,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'address': self.address
        }