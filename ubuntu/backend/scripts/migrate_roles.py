import logging
import uuid
import psycopg2
from tenants.loader import load_municipality_configs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migrate_roles")

def migrate():
    configs = load_municipality_configs()
    logger.info(f"Loaded {len(configs)} municipality configurations.")
    
    for config in configs:
        if not config.active:
            logger.info(f"Skipping inactive municipality: {config.name}")
            continue
            
        logger.info(f"Migrating roles for municipality: {config.name} (DB: {config.db.db_name})")
        
        db_params = {
            "host": config.db.host,
            "port": config.db.port,
            "dbname": config.db.db_name,
            "user": config.db.user,
            "password": config.db.password,
            "sslmode": config.db.sslmode,
        }
        
        # Override to connect inside docker container or outside
        # Inside docker, config.db.host 'db' is correct.
        
        try:
            conn = psycopg2.connect(**db_params)
            app_schema = config.schemas.app
            
            with conn.cursor() as cur:
                # 1. Insert 'lider_tecnico' if not exists
                cur.execute(
                    f"SELECT t_id FROM {app_schema}.roles WHERE itf_code = %s",
                    ('lider_tecnico',)
                )
                row = cur.fetchone()
                if not row:
                    new_uuid = str(uuid.uuid4())
                    cur.execute(
                        f"""
                        INSERT INTO {app_schema}.roles (itf_code, dispname, descripcion, t_ili_tid)
                        VALUES (%s, %s, %s, %s)
                        RETURNING t_id
                        """,
                        (
                            'lider_tecnico',
                            'Líder Técnico',
                            'Realiza control de calidad de XTF final y sincroniza la base de datos de producción.',
                            new_uuid
                        )
                    )
                    lider_tecnico_id = cur.fetchone()[0]
                    logger.info(f"Inserted role 'lider_tecnico' with t_id={lider_tecnico_id} in {app_schema}")
                else:
                    lider_tecnico_id = row[0]
                    logger.info(f"Role 'lider_tecnico' already exists with t_id={lider_tecnico_id} in {app_schema}")
                
                # 2. Update users with rol='lider_reconocimiento' to 'lider_tecnico'
                cur.execute(
                    f"""
                    UPDATE {app_schema}.users
                    SET rol = %s,
                        rol_id = %s
                    WHERE LOWER(rol) = 'lider_reconocimiento'
                    """,
                    ('lider_tecnico', lider_tecnico_id)
                )
                logger.info(f"Updated {cur.rowcount} users from 'lider_reconocimiento' to 'lider_tecnico' in {app_schema}")
                
                # 3. Update 'digitalizador' display name and description
                cur.execute(
                    f"""
                    UPDATE {app_schema}.roles
                    SET dispname = %s,
                        descripcion = %s
                    WHERE itf_code = %s
                    """,
                    (
                        'Digitalizador / Consolidador',
                        'Revisión, ajuste, validación y consolidación de la información catastral de campo.',
                        'digitalizador'
                    )
                )
                logger.info(f"Updated display name for 'digitalizador' in {app_schema}")
                
            conn.commit()
            conn.close()
            logger.info(f"Successfully migrated municipality: {config.name}")
        except Exception as exc:
            logger.error(f"Failed to migrate municipality {config.name}: {exc}")

if __name__ == "__main__":
    migrate()
