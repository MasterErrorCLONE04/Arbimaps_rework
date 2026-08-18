
with open("ubuntu/backend/services/asignaciones_workspace.py", "r", encoding="utf-8") as f:
    content = f.read()

target1 = """            if not exists:
                importar_predio_f_r1_r2_a_workspace(conn, tenant, npn, target_schema, t_basket_id)"""

replacement1 = """            if not exists:
                sp_name = f"sp_imp_predio_{abs(hash(npn)) % 10000000}"
                try:
                    cur.execute(f"SAVEPOINT {sp_name};")
                    importar_predio_f_r1_r2_a_workspace(conn, tenant, npn, target_schema, t_basket_id)
                    cur.execute(f"RELEASE SAVEPOINT {sp_name};")
                except Exception as imp_err:
                    try:
                        cur.execute(f"ROLLBACK TO SAVEPOINT {sp_name};")
                    except Exception:
                        pass
                    logger.warning("Error importando predio %s a %s: %s", npn, target_schema, imp_err)"""

if target1 in content:
    content = content.replace(target1, replacement1, 1)

target2 = """        safe_log_event(
            asignacion_id,
            "WORKSPACE_ON_DEMAND_SQL","""

replacement2 = """        safe_log_event(
            conn,
            tenant,
            asignacion_id,
            "WORKSPACE_ON_DEMAND_SQL","""

if target2 in content:
    content = content.replace(target2, replacement2, 1)

with open("ubuntu/backend/services/asignaciones_workspace.py", "w", encoding="utf-8") as f:
    f.write(content)

print("PATCH_APPLIED_ASIGNACIONES_WORKSPACE")

