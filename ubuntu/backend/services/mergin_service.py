import os
import fiona
import geopandas as gpd


# =========================================================
# Ã°Å¸â€Â NORMALIZAR TEXTO
# =========================================================
def normalize_text(value):
    if value is None:
        return ""

    text = str(value).strip()

    if text.lower() in ["nan", "none", "null", ""]:
        return ""

    return text


# =========================================================
# Ã°Å¸â€œÂ CREAR CARPETEO
# =========================================================
def create_carpeteo(create_folder, root_id, numero_predial):
    print(f"Ã°Å¸â€œÂ Creando estructura para: {numero_predial}")

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

    print("Ã¢Å“â€¦ Carpeteo completo")

    return {
        "root": predial_id,
        "doc": doc_id,
        "img": img_id,
        "colin": colin_id,
        "lpp": lpp_id
    }


# =========================================================
# Ã°Å¸Â§Â¾ EXTRAER PREDIOS DESDE GPKG
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
        print(f"Ã¢ÂÅ’ Error listando capas en {gpkg_path}: {e}")
        return result

    print(f"Ã°Å¸â€œÅ¡ Capas detectadas en {gpkg_path}: {layers}")

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

    print(f"Ã°Å¸Å½Â¯ Capa elegida para predios: {target_layer}")

    if not target_layer:
        print(f"Ã¢Å¡Â Ã¯Â¸Â No se encontrÃƒÂ³ capa de predio en {gpkg_path}")
        return result

    try:
        gdf = gpd.read_file(gpkg_path, layer=target_layer)
    except Exception as e:
        print(f"Ã¢ÂÅ’ Error leyendo capa predio: {e}")
        return result

    print(f"Ã°Å¸â€Â Leyendo capa predio de {gpkg_path}")
    print(f"Ã°Å¸Â§Â¾ Columnas predio: {list(gdf.columns)}")

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
        print(f"Ã¢Å¡Â Ã¯Â¸Â No se detectaron columnas clave en predio. id_col={id_col}, npn_col={npn_col}")
        return result

    for _, row in gdf.iterrows():
        predio_id = normalize_text(row[id_col])
        npn = normalize_text(row[npn_col])

        if predio_id and npn:
            result[predio_id] = npn

    print(f"Ã¢Å“â€¦ Predios encontrados: {result}")
    return result


# =========================================================
# Ã°Å¸â€œÂ¸ EXTRAER FOTOS DESDE GPKG
# Devuelve:
# {
#   "AR004": [
#       "Fotos_Caracteristicas/registro_fotografico-AR004-xxx.jpg"
#   ]
# }
# =========================================================
# ADJUNTOS POR GPKG
# =========================================================
DOC_ATTACHMENT_GPKGS = {
    "arb_adjunto_fuente_administrativa.gpkg",
    "arb_adjunto_interesado.gpkg",
}

IMAGE_ATTACHMENT_GPKGS = {
    "arb_adjunto_punto_de_referencia.gpkg",
    "arb_adjunto_terreno.gpkg",
    "arb_adjunto_unidad_de_construccin.gpkg",
    "arb_adjunto_unidad_de_construccion.gpkg",
}


# =========================================================
# BUSCAR ARCHIVOS CLAVE EN PROYECTO LOCAL
# =========================================================
def find_project_files(local_project_path):
    predio_gpkg = None
    attachment_gpkgs = {
        "doc": [],
        "img": [],
    }
    pdfs = []
    images = []

    for root, dirs, files in os.walk(local_project_path):
        dirs[:] = [d for d in dirs if d != ".mergin"]

        for file in files:
            full_path = os.path.join(root, file)
            name = file.lower().strip()

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
                    "registro_fotografico",
                ]):
                    predio_gpkg = full_path

            elif name in DOC_ATTACHMENT_GPKGS:
                attachment_gpkgs["doc"].append(full_path)

            elif name in IMAGE_ATTACHMENT_GPKGS:
                attachment_gpkgs["img"].append(full_path)

            elif name.endswith(".pdf"):
                pdfs.append(full_path)

            elif name.endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff")):
                images.append(full_path)

    print(f"predio_gpkg detectado: {predio_gpkg}")
    print(f"GPKG adjuntos doc detectados: {len(attachment_gpkgs['doc'])}")
    print(f"GPKG adjuntos img detectados: {len(attachment_gpkgs['img'])}")
    print(f"PDFs detectados en proyecto: {len(pdfs)}")
    print(f"imagenes detectadas en proyecto: {len(images)}")

    return {
        "predio_gpkg": predio_gpkg,
        "attachment_gpkgs": attachment_gpkgs,
        "pdfs": pdfs,
        "images": images,
    }


# =========================================================
# EXTRAER ADJUNTOS DESDE GPKG
# Devuelve: {npn: [ruta_archivo]}
# =========================================================
def extract_attachments_from_gpkg(gpkg_path):
    result = {}

    try:
        layers = fiona.listlayers(gpkg_path)
    except Exception as e:
        print(f"Error listando capas en {gpkg_path}: {e}")
        return result

    print(f"Capas detectadas en {gpkg_path}: {layers}")

    for layer in layers:
        try:
            gdf = gpd.read_file(gpkg_path, layer=layer)
        except Exception as e:
            print(f"Error leyendo capa {layer} en {gpkg_path}: {e}")
            continue

        print(f"Leyendo capa adjuntos {layer} de {gpkg_path}")
        print(f"Columnas adjuntos: {list(gdf.columns)}")

        npn_col = None
        archivo_col = None

        for col in gdf.columns:
            c = col.lower().strip()

            if c == "npn" or "numero_predial" in c or "cedula_catastral" in c:
                npn_col = col

            if c == "archivo" or "archivo" in c or "adjunto" in c or "ruta" in c or "path" in c:
                archivo_col = col

        if not npn_col or not archivo_col:
            print(f"No se detectaron columnas npn/archivo en {gpkg_path}, capa={layer}. npn_col={npn_col}, archivo_col={archivo_col}")
            continue

        for _, row in gdf.iterrows():
            npn = normalize_text(row[npn_col])
            archivo = normalize_text(row[archivo_col])

            if npn and archivo:
                result.setdefault(npn, []).append(archivo)

    print(f"Adjuntos extraidos de {os.path.basename(gpkg_path)}: {sum(len(v) for v in result.values())}")
    return result


# =========================================================
# INDICE Y RESOLUCION DE ARCHIVOS DEL PROYECTO
# =========================================================
def build_project_file_index(local_project_path):
    def norm(value):
        return str(value).replace("\\", "/").strip().lower()

    index = {
        "all_files": [],
        "by_relpath": {},
        "by_basename": {},
        "by_stem": {},
    }

    for root, dirs, files in os.walk(local_project_path):
        dirs[:] = [d for d in dirs if d != ".mergin"]

        for file in files:
            abs_path = os.path.join(root, file)
            rel_path = os.path.relpath(abs_path, local_project_path)
            rel_norm = norm(rel_path)
            base = os.path.basename(file).lower().strip()
            stem = os.path.splitext(base)[0]

            index["all_files"].append(abs_path)
            index["by_relpath"].setdefault(rel_norm, []).append(abs_path)
            index["by_basename"].setdefault(base, []).append(abs_path)
            index["by_stem"].setdefault(stem, []).append(abs_path)

            parts = rel_norm.split("/")
            for i in range(len(parts)):
                suffix = "/".join(parts[i:])
                index["by_relpath"].setdefault(suffix, []).append(abs_path)

    print(f"Total archivos indexados: {len(index['all_files'])}")
    return index


def resolve_attachment_path(file_index, archivo, used_paths):
    clean = str(archivo).replace("\\", "/").strip().lower()
    file_name = os.path.basename(clean)
    file_stem = os.path.splitext(file_name)[0]

    candidates = []

    if clean in file_index["by_relpath"]:
        candidates.extend(file_index["by_relpath"][clean])

    if file_name in file_index["by_basename"]:
        candidates.extend(file_index["by_basename"][file_name])

    if file_stem in file_index["by_stem"]:
        candidates.extend(file_index["by_stem"][file_stem])

    if file_stem:
        for stem_key, stem_candidates in file_index["by_stem"].items():
            if file_stem in stem_key or stem_key in file_stem:
                candidates.extend(stem_candidates)

    for candidate in candidates:
        if candidate not in used_paths:
            return candidate

    return None


def merge_attachment_maps(target, source):
    for npn, paths in source.items():
        target.setdefault(npn, []).extend(paths)


def resolve_attachments_by_npn(local_project_path, attachment_paths_by_npn):
    resolved = {}
    file_index = build_project_file_index(local_project_path)

    for npn, archivos in attachment_paths_by_npn.items():
        used_paths = set()

        for archivo in archivos:
            print(f"Buscando adjunto para NPN {npn}: {archivo}")
            found = resolve_attachment_path(file_index, archivo, used_paths)

            if found:
                used_paths.add(found)
                resolved.setdefault(npn, []).append(found)
                print(f"Adjunto resuelto para NPN {npn}: {found}")
            else:
                print(f"No se encontro adjunto para NPN {npn}: {archivo}")

    return resolved


# =========================================================
# PROCESAR PROYECTO LOCAL Y CREAR CARPETEO
# =========================================================
def process_local_project_for_carpeteo(local_project_path, root_box_folder_id, create_folder, upload_file):
    files_info = find_project_files(local_project_path)

    predio_gpkg = files_info["predio_gpkg"]
    attachment_gpkgs = files_info["attachment_gpkgs"]

    if not predio_gpkg:
        print("No se encontro archivo GPKG principal de predio")
        return

    project_name = os.path.basename(local_project_path)
    print(f"\nCreando carpeta de proyecto en BOX: {project_name}")
    project_folder_id = create_folder(root_box_folder_id, project_name)

    predios = extract_predios_from_gpkg(predio_gpkg)

    if not predios:
        print("No se encontraron predios/NPN validos")
        return

    doc_paths_by_npn = {}
    img_paths_by_npn = {}

    for gpkg_path in attachment_gpkgs["doc"]:
        merge_attachment_maps(doc_paths_by_npn, extract_attachments_from_gpkg(gpkg_path))

    for gpkg_path in attachment_gpkgs["img"]:
        merge_attachment_maps(img_paths_by_npn, extract_attachments_from_gpkg(gpkg_path))

    doc_files_by_npn = resolve_attachments_by_npn(local_project_path, doc_paths_by_npn)
    img_files_by_npn = resolve_attachments_by_npn(local_project_path, img_paths_by_npn)

    print(f"Predios detectados (claves): {list(predios.keys())[:20]}")
    print(f"NPN con docs resueltos: {list(doc_files_by_npn.keys())[:20]}")
    print(f"NPN con imagenes resueltas: {list(img_files_by_npn.keys())[:20]}")

    for predio_id, npn in predios.items():
        predio_docs = doc_files_by_npn.get(npn, [])
        predio_images = img_files_by_npn.get(npn, [])

        print(f"\nProcesando predio {predio_id} -> NPN {npn}")
        print(f"NPN {npn} tiene {len(predio_docs)} documentos soporte asociados")
        print(f"NPN {npn} tiene {len(predio_images)} imagenes asociadas")

        if not predio_docs and not predio_images:
            print(f"Se omite NPN {npn}: sin documentos ni imagenes asociadas")
            continue

        structure = create_carpeteo(create_folder, project_folder_id, npn)

        for doc_path in predio_docs:
            print(f"DOC -> {doc_path}")
            upload_file(structure["doc"], doc_path)

        for img_path in predio_images:
            print(f"IMG -> {img_path}")
            upload_file(structure["img"], img_path)

        print("Carpeteo por NPN finalizado")


# =========================================================
# COMPATIBILIDAD CON TU FLUJO ACTUAL
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
                        print(f"Ã¢Å¡Â Ã¯Â¸Â Error leyendo gpkg temporal: {e}")

        return None

    try:
        print("Ã°Å¸â€Â Buscando NPN en BOX...")
        resultado = buscar_en_carpeta(folder_id)

        if resultado:
            return resultado

        return "SIN_NPN"

    except Exception as e:
        print("Ã¢ÂÅ’ ERROR leyendo BOX:", str(e))
        return "ERROR_NPN"