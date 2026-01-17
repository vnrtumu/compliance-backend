from typing import Any, Dict, Union
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

    def update(self, db: Session, *, db_obj: Upload, obj_in: Union[Dict[str, Any], Any]):
        """Update an upload record with new data."""
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.dict(exclude_unset=True)
        
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

upload = CRUDUpload()

