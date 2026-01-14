from sqlalchemy.orm import Session
from app.models.upload import Upload
from app.schemas.upload import UploadCreate

class CRUDUpload:
    def get(self, db: Session, id: int):
        return db.query(Upload).filter(Upload.id == id).first()

    def get_multi(self, db: Session, *, skip: int = 0, limit: int = 100):
        return db.query(Upload).order_by(Upload.created_at.desc()).offset(skip).limit(limit).all()

    def create(self, db: Session, *, obj_in: UploadCreate):
        db_obj = Upload(
            filename=obj_in.filename,
            content_type=obj_in.content_type,
            size=obj_in.size,
            storage_path=obj_in.storage_path
        )
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

upload = CRUDUpload()
