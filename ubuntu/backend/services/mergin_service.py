import os
import fiona
import geopandas as gpd


# =========================================================
# 🔍 NORMALIZAR TEXTO
# =========================================================
def normalize_text(value):
    if value is None:
        return ""

    text = str(value).strip()

    if text.lower() in ["nan", "none", "null", ""]:
        return ""

    return text


# =========================================================
# 📁 CREAR CARPETEO
# =========================================================
def create_carpeteo(create_folder, root_id, numero_predial):
    print(f"📁 Creando estructura para: {numero_predial}")

    predial_id = create_folder(root_id, numero_predial)

    colin_id = create_folder(predial_id, "01_colin")
    doc_id = create_folder(predial_id, "02_doc_sop")
    img_id = create_folder(predial_id, "03_img")
    lpp_id = create_folder(predial_id, "04_lpp")

    create_folder(lpp_id, "01_repor_calid_lpp")
    create_folder(lpp_id, "02_postproc")
    create_folder(lpp_id, "03_img_vert")

    gnss_id = create_folder(lpp_id, "04_arch_GNSS")
    create_folder(gnss_id, "01_base")
    create_folder(gnss_id, "02_pto_GPS")

    print("✅ Carpeteo completo")

    return {
        "root": predial_id,
        "doc": doc_id,
        "img": img_id,
        "colin": colin_id,
        "lpp": lpp_id
    }


# =========================================================
# 🧾 EXTRAER PREDIOS DESDE GPKG
# Devuelve:
# {
#   "AR001": "73055....",
#   "AR002": "73055...."
# }
# =========================================================
def extract_predios_from_gpkg(gpkg_path):
    result = {}

    try:
        layers = fiona.listlayers(gpkg_path)
    except Exception as e:
        print(f"❌ Error listando capas en {gpkg_path}: {e}")
        return result

    print(f"📚 Capas detectadas en {gpkg_path}: {layers}")

    target_layer = None

    # exacta
    for layer in layers:
        if layer.lower().strip() == "predio":
            target_layer = layer
            break

    # fallback conocidos
    if not target_layer:
        for layer in layers:
            lname = layer.lower().strip()
            if lname in ["arb_predio", "predio__cca_predio", "predio_cca_predio"]:
                target_layer = layer
                break

    # fallback flexible
    if not target_layer:
        for layer in layers:
            lname = layer.lower().strip()
            if lname.endswith("__predio") or lname.endswith("_predio") or "predio" in lname:
                if not any(x in lname for x in [
                    "servicios_predio",
                    "visita_predio",
                    "area_predio",
                    "datos_adicionales_predio",
                    "info_economica_predio",
                    "registro_fotografico"
                ]):
                    target_layer = layer
                    break

    print(f"🎯 Capa elegida para predios: {target_layer}")

    if not target_layer:
        print(f"⚠️ No se encontró capa de predio en {gpkg_path}")
        return result

    try:
        gdf = gpd.read_file(gpkg_path, layer=target_layer)
    except Exception as e:
        print(f"❌ Error leyendo capa predio: {e}")
        return result

    print(f"🔍 Leyendo capa predio de {gpkg_path}")
    print(f"🧾 Columnas predio: {list(gdf.columns)}")

    id_col = None
    npn_col = None

    for col in gdf.columns:
        c = col.lower().strip()

        if c in ["id predio", "id_predio", "idpredio"]:
            id_col = col

        if c in ["cedula catastral", "cedula_catastral", "numero_predial", "npn", "npn_campo"]:
            npn_col = col

    # fallback id
    if not id_col:
        for col in gdf.columns:
            c = col.lower().strip()
            if c in ["t_id", "uuid_predio", "uuid", "id_operacion", "fid"]:
                id_col = col
                break

    if not id_col:
        for col in gdf.columns:
            c = col.lower().strip()
            if "id" in c:
                id_col = col
                break

    # fallback npn
    if not npn_col:
        for col in gdf.columns:
            c = col.lower().strip()
            if "predial" in c or "catastral" in c or c == "npn" or "npn" in c:
                npn_col = col
                break

    if not id_col or not npn_col:
        print(f"⚠️ No se detectaron columnas clave en predio. id_col={id_col}, npn_col={npn_col}")
        return result

    for _, row in gdf.iterrows():
        predio_id = normalize_text(row[id_col])
        npn = normalize_text(row[npn_col])

        if predio_id and npn:
            result[predio_id] = npn

    print(f"✅ Predios encontrados: {result}")
    return result


# =========================================================
# 📸 EXTRAER FOTOS DESDE GPKG
# Devuelve:
# {
#   "AR004": [
#       "Fotos_Caracteristicas/registro_fotografico-AR004-xxx.jpg"
#   ]
# }
# =========================================================
def extract_fotos_from_gpkg(gpkg_path):
    result = {}

    try:
        layers = fiona.listlayers(gpkg_path)
    except Exception as e:
        print(f"❌ Error listando capas en {gpkg_path}: {e}")
        return result

    print(f"📚 Capas detectadas en {gpkg_path}: {layers}")

    target_layer = None
    for layer in layers:
        lname = layer.lower().strip()
        if lname == "registro_fotografico" or "registro_fotografico" in lname:
            target_layer = layer
            break

    print(f"🎯 Capa elegida para fotos: {target_layer}")

    if not target_layer:
        print(f"⚠️ No se encontró capa 'registro_fotografico' en {gpkg_path}")
        return result

    try:
        gdf = gpd.read_file(gpkg_path, layer=target_layer)
    except Exception as e:
        print(f"❌ Error leyendo capa registro_fotografico: {e}")
        return result

    print(f"🔍 Leyendo capa registro_fotografico de {gpkg_path}")
    print(f"🧾 Columnas registro_fotografico: {list(gdf.columns)}")

    id_col = None
    foto_col = None

    for col in gdf.columns:
        c = col.lower().strip()

        if c in ["id predio", "id_predio", "idpredio"]:
            id_col = col

        if c in ["registro foto", "registro_foto", "foto", "path_foto", "adjunto"]:
            foto_col = col

    if not id_col:
        for col in gdf.columns:
            c = col.lower().strip()
            if "id" in c and "predio" in c:
                id_col = col
                break

    if not foto_col:
        for col in gdf.columns:
            c = col.lower().strip()
            if "foto" in c or "imagen" in c or "path" in c or "adjunto" in c:
                foto_col = col
                break

    if not id_col or not foto_col:
        print(f"⚠️ No se detectaron columnas clave en registro_fotografico. id_col={id_col}, foto_col={foto_col}")
        return result

    for _, row in gdf.iterrows():
        predio_id = normalize_text(row[id_col])
        foto_path = normalize_text(row[foto_col])

        if predio_id and foto_path:
            result.setdefault(predio_id, []).append(foto_path)

    print(f"✅ Fotos por predio: {result}")
    return result


# =========================================================
# 📂 BUSCAR ARCHIVOS CLAVE EN PROYECTO LOCAL
# =========================================================
def find_project_files(local_project_path):
    predio_gpkg = None
    registro_gpkg = None
    pdfs = []
    images = []

    for root, dirs, files in os.walk(local_project_path):
        dirs[:] = [d for d in dirs if d != ".mergin"]

        for file in files:
            full_path = os.path.join(root, file)
            name = file.lower()

            if name.endswith(".gpkg") and (
                name == "predio.gpkg" or
                name == "arb_predio.gpkg" or
                name.endswith("__predio.gpkg") or
                name.endswith("_predio.gpkg")
            ):
                if not any(x in name for x in [
                    "servicios_predio",
                    "visita_predio",
                    "area_predio",
                    "datos_adicionales_predio",
                    "info_economica_predio",
                    "registro_fotografico"
                ]):
                    predio_gpkg = full_path

            elif name.endswith(".gpkg") and "registro_fotografico" in name:
                registro_gpkg = full_path

            elif name.endswith(".pdf"):
                pdfs.append(full_path)

            elif name.endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff")):
                images.append(full_path)

    print(f"📌 predio_gpkg detectado: {predio_gpkg}")
    print(f"📌 registro_gpkg detectado: {registro_gpkg}")
    print(f"📌 PDFs detectados: {len(pdfs)}")
    print(f"📌 imágenes detectadas: {len(images)}")

    return {
        "predio_gpkg": predio_gpkg,
        "registro_gpkg": registro_gpkg,
        "pdfs": pdfs,
        "images": images
    }


# =========================================================
# 📸 RESOLVER RUTAS DE FOTOS
# =========================================================
def resolve_photo_paths(local_project_path, fotos_by_predio):
    import os

    resolved = {}

    def norm(s):
        return str(s).replace("\\", "/").strip().lower()

    # -------------------------------------------------
    # Índices robustos de todas las imágenes del proyecto
    # -------------------------------------------------
    all_files = []
    by_basename = {}
    by_stem = {}
    by_relpath = {}

    for root, dirs, files in os.walk(local_project_path):
        dirs[:] = [d for d in dirs if d != ".mergin"]

        for f in files:
            fl = f.lower()
            if fl.endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff")):
                abs_path = os.path.join(root, f)
                rel_path = os.path.relpath(abs_path, local_project_path)

                all_files.append(abs_path)

                base = os.path.basename(f).lower()
                stem = os.path.splitext(base)[0]

                by_basename.setdefault(base, []).append(abs_path)
                by_stem.setdefault(stem, []).append(abs_path)

                # guardar varias formas de ruta relativa
                rel_norm = norm(rel_path)
                by_relpath.setdefault(rel_norm, []).append(abs_path)

                # también por si viene con carpetas internas raras
                parts = rel_norm.split("/")
                for i in range(len(parts)):
                    suffix = "/".join(parts[i:])
                    by_relpath.setdefault(suffix, []).append(abs_path)

    print(f"🗂️ Total imágenes indexadas: {len(all_files)}")

    # -------------------------------------------------
    # Resolver fotos por predio
    # -------------------------------------------------
    for predio_id, paths in fotos_by_predio.items():
        usados = set()

        for rel_path in paths:
            clean_rel = norm(rel_path)
            file_name = os.path.basename(clean_rel)
            file_stem = os.path.splitext(file_name)[0]

            found = None

            print(f"🔎 Buscando foto para {predio_id}: {clean_rel}")

            # 1. ruta relativa exacta
            if clean_rel in by_relpath:
                for candidate in by_relpath[clean_rel]:
                    if candidate not in usados:
                        found = candidate
                        break

            # 2. basename exacto
            if not found and file_name in by_basename:
                for candidate in by_basename[file_name]:
                    if candidate not in usados:
                        found = candidate
                        break

            # 3. stem exacto
            if not found and file_stem in by_stem:
                for candidate in by_stem[file_stem]:
                    if candidate not in usados:
                        found = candidate
                        break

            # 4. coincidencia parcial fuerte por stem
            if not found and file_stem:
                for stem_key, candidates in by_stem.items():
                    if file_stem in stem_key or stem_key in file_stem:
                        for candidate in candidates:
                            if candidate not in usados:
                                found = candidate
                                break
                    if found:
                        break

            if found:
                usados.add(found)
                resolved.setdefault(predio_id, []).append(found)
                print(f"✅ Foto resuelta para {predio_id}: {found}")
            else:
                print(f"⚠️ No se encontró foto para {predio_id}: {clean_rel}")

    return resolved

# =========================================================
# 📦 PROCESAR PROYECTO LOCAL Y CREAR CARPETEO
# =========================================================
def process_local_project_for_carpeteo(local_project_path, root_box_folder_id, create_folder, upload_file):
    files_info = find_project_files(local_project_path)

    predio_gpkg = files_info["predio_gpkg"]
    registro_gpkg = files_info["registro_gpkg"]
    pdfs = files_info["pdfs"]

    if not predio_gpkg:
        print("❌ No se encontró archivo GPKG principal de predio")
        return

    project_name = os.path.basename(local_project_path)
    print(f"\n📦 Creando carpeta de proyecto en BOX: {project_name}")
    project_folder_id = create_folder(root_box_folder_id, project_name)

    predios = extract_predios_from_gpkg(predio_gpkg)

    if not predios:
        print("⚠️ No se encontraron predios/NPN válidos")
        return

    fotos_by_predio = {}
    if registro_gpkg:
        fotos_by_predio = extract_fotos_from_gpkg(registro_gpkg)

    fotos_resueltas = resolve_photo_paths(local_project_path, fotos_by_predio)
    for k, v in fotos_resueltas.items():
        print(f"📸 Predio {k} -> fotos resueltas: {len(v)}")

    print(f"🧩 Predios detectados (claves): {list(predios.keys())[:20]}")
    print(f"🧩 Fotos resueltas (claves): {list(fotos_resueltas.keys())[:20]}")

    for predio_id, npn in predios.items():
        predio_images = fotos_resueltas.get(predio_id, [])

        print(f"\n🚀 Procesando predio {predio_id} -> NPN {npn}")
        print(f"🔗 Predio {predio_id} tiene {len(predio_images)} imágenes asociadas")

        # 🔥 CLAVE: si no hay nada que subir, NO crear estructura
        if not pdfs and not predio_images:
            print(f"⏭️ Se omite NPN {npn}: sin PDFs ni imágenes asociadas")
            continue

        structure = create_carpeteo(create_folder, project_folder_id, npn)

        for pdf_path in pdfs:
            print(f"📄 PDF -> {pdf_path}")
            upload_file(structure["doc"], pdf_path)

        for img_path in predio_images:
            print(f"🖼️ IMG {predio_id} -> {img_path}")
            upload_file(structure["img"], img_path)

        print("✅ Carpeteo por NPN finalizado")
# =========================================================
# 🔥 COMPATIBILIDAD CON TU FLUJO ACTUAL
# =========================================================
def get_npn_from_box(download_file_func, folder_items_func, folder_id):
    import tempfile

    def buscar_en_carpeta(folder_id):
        items = folder_items_func(folder_id)

        for item in items:
            if item["type"] == "folder":
                resultado = buscar_en_carpeta(item["id"])
                if resultado:
                    return resultado

            elif item["type"] == "file" and item["name"].endswith(".gpkg"):
                with tempfile.NamedTemporaryFile(suffix=".gpkg") as tmp:
                    download_file_func(item["id"], tmp.name)

                    try:
                        predios = extract_predios_from_gpkg(tmp.name)
                        if predios:
                            return list(predios.values())[0]
                    except Exception as e:
                        print(f"⚠️ Error leyendo gpkg temporal: {e}")

        return None

    try:
        print("🔍 Buscando NPN en BOX...")
        resultado = buscar_en_carpeta(folder_id)

        if resultado:
            return resultado

        return "SIN_NPN"

    except Exception as e:
        print("❌ ERROR leyendo BOX:", str(e))
        return "ERROR_NPN"