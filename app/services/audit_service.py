from database import db, AuditLog

def log_action(user_id, action, details=""):
    log = AuditLog(
        user_id=user_id,
        action=action,
        details=details
    )
    db.session.add(log)
    db.session.commit()