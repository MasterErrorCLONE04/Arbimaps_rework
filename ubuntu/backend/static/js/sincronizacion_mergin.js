(function () {
  const connectionForm = document.getElementById("merginConnectionForm");
  const connectionStatus = document.getElementById("connectionStatus");
  const schemaStatus = document.getElementById("schemaStatus");
  const databaseInput = document.getElementById("database");
  const schemaSelect = document.getElementById("schemaSelect");
  const schemaTableBody = document.getElementById("schemaTableBody");
  const btnTestConnection = document.getElementById("btnTestConnection");
  const zipFileInput = document.getElementById("zipFileInput");
  const btnAnalyzeZip = document.getElementById("btnAnalyzeZip");
  const zipStatus = document.getElementById("zipStatus");
  const zipAnalysisPanel = document.getElementById("zipAnalysisPanel");
  const zipCompatibilityPill = document.getElementById("zipCompatibilityPill");
  const zipCompatibilityDetail = document.getElementById("zipCompatibilityDetail");
  const zipGpkgTableBody = document.getElementById("zipGpkgTableBody");
  const zipTransferableTableBody = document.getElementById("zipTransferableTableBody");
  const zipMissingTableBody = document.getElementById("zipMissingTableBody");
  const zipIgnoredTableBody = document.getElementById("zipIgnoredTableBody");
  const stagingSchemaInput = document.getElementById("stagingSchemaInput");
  const replaceStagingCheckbox = document.getElementById("replaceStagingCheckbox");
  const btnDryRunImport = document.getElementById("btnDryRunImport");
  const btnImportStaging = document.getElementById("btnImportStaging");
  const stagingStatus = document.getElementById("stagingStatus");
  const stagingReportPanel = document.getElementById("stagingReportPanel");
  const stagingImportedTableBody = document.getElementById("stagingImportedTableBody");
  const stagingIgnoredTableBody = document.getElementById("stagingIgnoredTableBody");
  const stagingMissingTableBody = document.getElementById("stagingMissingTableBody");

  if (!connectionForm || !connectionStatus || !schemaStatus || !databaseInput || !schemaSelect || !schemaTableBody) {
    return;
  }

  let connectionState = null;

  function formatApiError(data, response) {
    if (!data || typeof data !== "object") {
      return `HTTP ${response.status}`;
    }
    const parts = [];
    if (data.error_type) {
      parts.push(String(data.error_type));
    }
    if (data.message) {
      parts.push(String(data.message));
    } else if (typeof data.detail === "string") {
      parts.push(String(data.detail));
    }
    if (data.detail && typeof data.detail === "object") {
      const detailText = [data.detail.pgerror, data.detail.repr].filter(Boolean).join(" | ");
      if (detailText) {
        parts.push(detailText);
      }
    }
    return parts.join(": ") || `HTTP ${response.status}`;
  }

  function setStatus(element, kind, message) {
    element.className = `mergin-sync-status ${kind}`;
    element.textContent = message;
  }

  function resetSchemaUi(message) {
    schemaSelect.innerHTML = '<option value="">Selecciona una base de datos</option>';
    schemaSelect.disabled = true;
    schemaTableBody.innerHTML = `<tr><td colspan="4" class="is-empty">${message}</td></tr>`;
  }

  function buildPayload(extra = {}) {
    const formData = new FormData(connectionForm);
    return {
      host: String(formData.get("host") || "").trim(),
      port: Number(formData.get("port") || 5432),
      user: String(formData.get("user") || "").trim(),
      password: String(formData.get("password") || ""),
      database: String(document.getElementById("database")?.value || "").trim(),
      ...extra,
    };
  }

  function deriveStagingSchema(targetSchema, databaseName) {
    const target = String(targetSchema || "").trim();
    if (target.startsWith("asignacion_")) {
      const parts = target.split("_");
      if (parts.length >= 3) {
        return `transferencia_${parts[1]}_${parts[2]}`;
      }
    }
    const database = String(databaseName || "").trim().replace(/[^a-zA-Z0-9_]+/g, "_");
    return database ? `transferencia_${database}` : "transferencia_staging";
  }

  function syncSuggestedStagingSchema(force = false) {
    if (!stagingSchemaInput) {
      return;
    }
    const suggested = deriveStagingSchema(schemaSelect.value, databaseInput.value);
    if (force || !stagingSchemaInput.value.trim()) {
      stagingSchemaInput.value = suggested;
    }
  }

  async function postJson(url, payload) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(formatApiError(data, response));
    }
    return data;
  }

  async function postFormData(url, formData) {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      body: formData,
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(formatApiError(data, response));
    }
    return data;
  }

  function renderSchemas(items) {
    if (!Array.isArray(items) || items.length === 0) {
      schemaTableBody.innerHTML = '<tr><td colspan="4" class="is-empty">La base seleccionada no devolvio schemas visibles.</td></tr>';
      return;
    }

    schemaTableBody.innerHTML = items.map((item) => {
      const statusClass = item.is_compatible ? "ok" : item.has_partial_match ? "warn" : "no";
      const statusText = item.is_compatible ? "Compatible" : item.has_partial_match ? "Parcial" : "No compatible";
      const required = Array.isArray(item.required_tables_present) && item.required_tables_present.length
        ? item.required_tables_present.join(", ")
        : "Sin tablas clave";
      const detail = item.is_compatible
        ? "Cumple tablas base de workspace."
        : item.has_partial_match
          ? `Faltan: ${(item.required_tables_missing || []).join(", ")}`
          : "No contiene tablas base detectadas.";

      return `
        <tr>
          <td><strong>${item.schema}</strong></td>
          <td><span class="mergin-sync-pill ${statusClass}">${statusText}</span></td>
          <td>${required}</td>
          <td>${detail}</td>
        </tr>
      `;
    }).join("");
  }

  async function loadSchemas(databaseName) {
    if (!connectionState || !databaseName) {
      return;
    }

    schemaSelect.disabled = true;
    schemaSelect.innerHTML = '<option value="">Cargando schemas...</option>';
    setStatus(schemaStatus, "neutral", `Consultando schemas de ${databaseName}...`);

    try {
      const data = await postJson(`${window.rp}/api/sincronizacion-mergin/list-schemas`, {
        ...connectionState,
        database: databaseName,
      });

      const schemas = Array.isArray(data.schemas) ? data.schemas : [];
      if (!schemas.length) {
        schemaSelect.innerHTML = '<option value="">No se encontraron schemas</option>';
        schemaSelect.disabled = true;
        setStatus(schemaStatus, "error", "La base seleccionada no contiene schemas utilizables.");
        renderSchemas([]);
        return;
      }

      schemaSelect.innerHTML = '<option value="">Selecciona un schema destino</option>' + schemas.map((item) => {
        const suffix = item.is_compatible ? "compatible" : item.has_partial_match ? "parcial" : "no compatible";
        return `<option value="${item.schema}">${item.schema} (${suffix})</option>`;
      }).join("");
      schemaSelect.disabled = false;
      renderSchemas(schemas);
      syncSuggestedStagingSchema(true);

      const compatibleCount = schemas.filter((item) => item.is_compatible).length;
      setStatus(
        schemaStatus,
        compatibleCount > 0 ? "success" : "neutral",
        compatibleCount > 0
          ? `Se encontraron ${compatibleCount} schema(s) compatibles en ${databaseName}.`
          : `No hay schemas plenamente compatibles en ${databaseName}; revisa el detalle.`
      );
    } catch (error) {
      schemaSelect.innerHTML = '<option value="">No se pudieron cargar schemas</option>';
      schemaSelect.disabled = true;
      renderSchemas([]);
      setStatus(schemaStatus, "error", error.message || "No se pudieron cargar los schemas.");
    }
  }

  function setText(elementId, value, fallback = "No disponible") {
    const element = document.getElementById(elementId);
    if (!element) {
      return;
    }
    element.textContent = value ? String(value) : fallback;
  }

  function renderRows(tableBody, html, colspan, emptyMessage) {
    if (!tableBody) {
      return;
    }
    tableBody.innerHTML = html || `<tr><td colspan="${colspan}" class="is-empty">${emptyMessage}</td></tr>`;
  }

  function renderNoteList(elementId, items, kind) {
    const element = document.getElementById(elementId);
    if (!element) {
      return;
    }
    if (!Array.isArray(items) || !items.length) {
      element.innerHTML = "";
      return;
    }
    element.innerHTML = items.map((item) => `<div class="mergin-sync-note ${kind}">${item}</div>`).join("");
  }

  function renderZipAnalysis(data) {
    if (!zipAnalysisPanel || !zipCompatibilityPill || !zipCompatibilityDetail) {
      return;
    }

    zipAnalysisPanel.hidden = false;

    const metadata = data.metadata || {};
    const summary = data.summary || {};
    const compatibility = data.compatibility || "No compatible";
    const transferableLayers = Array.isArray(data.transferable_layers) ? data.transferable_layers : [];
    const ignoredLayers = Array.isArray(data.ignored_layers) ? data.ignored_layers : [];
    const missingLayers = Array.isArray(data.missing_transferable_layers) ? data.missing_transferable_layers : [];
    const missingRequiredLayers = Array.isArray(data.missing_required_layers) ? data.missing_required_layers : [];
    const gpkgFiles = Array.isArray(data.gpkg_files) ? data.gpkg_files : [];
    const statusClass = compatibility === "Compatible" ? "ok" : compatibility === "Compatible parcial" ? "warn" : "no";

    zipCompatibilityPill.className = `mergin-sync-pill ${statusClass}`;
    zipCompatibilityPill.textContent = compatibility;
    zipCompatibilityDetail.textContent = compatibility === "Compatible"
      ? "Se encontraron todas las capas geograficas base requeridas para continuar a Fase 4."
      : compatibility === "Compatible parcial"
        ? `Faltan capas base: ${missingRequiredLayers.join(", ") || "sin detalle"}.`
        : "No se encontro ninguna capa transferible de la whitelist en los GPKG analizados.";

    setText("zipProject", metadata.project);
    setText("zipWorkspace", metadata.workspace);
    setText("zipVersion", metadata.version);
    setText("zipUser", metadata.user);
    setText("zipDate", metadata.date);
    setText("zipFileName", data.zip_name);
    setText("zipMetadataFile", data.metadata_file, "No encontrada");
    setText("zipProjectFile", data.project_file, "No encontrado");
    setText("zipAttachments", data.attachments_path, "No encontrados");
    setText("zipTotalGpkg", summary.total_gpkg ?? 0, "0");
    setText("zipTransferableRecords", Number(summary.transferable_records || 0).toLocaleString("es-CO"), "0");
    setText("zipIgnoredRecords", Number(summary.ignored_records || 0).toLocaleString("es-CO"), "0");

    renderRows(
      zipGpkgTableBody,
      gpkgFiles.map((item) => `
        <tr>
          <td><strong>${item.gpkg || "Sin ruta"}</strong></td>
          <td><span class="mergin-sync-pill ${item.category === "transferable" ? "ok" : "warn"}">${item.category === "transferable" ? "Transferible" : "Ignorado"}</span></td>
          <td>${Number(item.transferable_layers || 0).toLocaleString("es-CO")}</td>
          <td>${Number(item.ignored_layers || 0).toLocaleString("es-CO")}</td>
          <td>${Number(item.transferable_records || 0).toLocaleString("es-CO")}</td>
          <td>${Number(item.ignored_records || 0).toLocaleString("es-CO")}</td>
        </tr>
      `).join(""),
      6,
      "Los GPKG analizados apareceran aqui."
    );

    renderRows(
      zipTransferableTableBody,
      transferableLayers.map((layer) => `
        <tr>
          <td><strong>${layer.name || "Sin nombre"}</strong></td>
          <td>${layer.gpkg || ""}</td>
          <td>${Number(layer.records || 0).toLocaleString("es-CO")}</td>
          <td>${layer.geometry || "Sin geometria"}</td>
          <td>${layer.crs || "No disponible"}</td>
        </tr>
      `).join(""),
      5,
      "No se encontraron capas transferibles en la whitelist."
    );

    renderRows(
      zipMissingTableBody,
      missingLayers.map((name) => `
        <tr>
          <td><strong>${name}</strong></td>
          <td><span class="mergin-sync-pill no">Faltante</span></td>
          <td>${missingRequiredLayers.includes(name) ? "Base" : "Complementaria"}</td>
          <td>${missingRequiredLayers.includes(name) ? "Afecta la compatibilidad base del proyecto." : "No fue encontrada en ninguno de los GPKG analizados."}</td>
        </tr>
      `).join(""),
      4,
      "No hay capas transferibles esperadas pendientes por encontrar."
    );

    renderRows(
      zipIgnoredTableBody,
      ignoredLayers.map((layer) => `
        <tr>
          <td><strong>${layer.name || "Sin nombre"}</strong></td>
          <td>${layer.gpkg || ""}</td>
          <td>${Number(layer.records || 0).toLocaleString("es-CO")}</td>
          <td>${layer.geometry || "Sin geometria"}</td>
          <td>${layer.reason || "Sin detalle"}</td>
        </tr>
      `).join(""),
      5,
      "No se detectaron capas ignoradas."
    );
  }

  function renderStagingReport(data) {
    if (!stagingReportPanel) {
      return;
    }

    stagingReportPanel.hidden = false;

    const summary = data.summary || {};
    const importedLayers = Array.isArray(data.imported_layers) ? data.imported_layers : [];
    const ignoredLayers = Array.isArray(data.ignored_layers) ? data.ignored_layers : [];
    const missingLayers = Array.isArray(data.missing_layers) ? data.missing_layers : [];
    const warnings = Array.isArray(data.warnings) ? data.warnings : [];
    const errors = Array.isArray(data.errors) ? data.errors : [];

    setText("stagingMode", data.mode || "No ejecutado");
    setText("stagingTargetSchema", data.target_schema || "No seleccionado");
    setText("stagingSchemaName", data.staging_schema || "No definido");
    setText("stagingSchemaCreated", data.created_schema ? "Si" : "No");
    setText("stagingImportedCount", Number(summary.imported_layers || 0).toLocaleString("es-CO"), "0");
    setText("stagingImportedRecords", Number(summary.imported_records || 0).toLocaleString("es-CO"), "0");
    setText("stagingIgnoredCount", Number(summary.ignored_layers || 0).toLocaleString("es-CO"), "0");
    setText("stagingMissingCount", Number(summary.missing_layers || 0).toLocaleString("es-CO"), "0");
    setText("stagingWarningsCount", Number(warnings.length || 0).toLocaleString("es-CO"), "0");
    setText("stagingErrorsCount", Number(errors.length || 0).toLocaleString("es-CO"), "0");

    renderRows(
      stagingImportedTableBody,
      importedLayers.map((layer) => {
        const statusClass = layer.status === "imported" ? "ok" : layer.status === "planned" ? "warn" : "no";
        return `
          <tr>
            <td><strong>${layer.name || "Sin nombre"}</strong></td>
            <td>${layer.table || ""}</td>
            <td><span class="mergin-sync-pill ${statusClass}">${layer.status || "sin estado"}</span></td>
            <td>${Number(layer.records || 0).toLocaleString("es-CO")}</td>
            <td>${layer.geometry || "Sin geometria"}</td>
            <td>${layer.srid ?? "No disponible"}</td>
          </tr>
        `;
      }).join(""),
      6,
      "El reporte de capas importadas aparecera aqui."
    );

    renderRows(
      stagingIgnoredTableBody,
      ignoredLayers.map((layer) => `
        <tr>
          <td><strong>${layer.name || "Sin nombre"}</strong></td>
          <td>${layer.gpkg || ""}</td>
          <td>${Number(layer.records || 0).toLocaleString("es-CO")}</td>
          <td>${layer.reason || "Sin detalle"}</td>
        </tr>
      `).join(""),
      4,
      "Las capas ignoradas apareceran aqui."
    );

    renderRows(
      stagingMissingTableBody,
      missingLayers.map((name) => `
        <tr>
          <td><strong>${name}</strong></td>
        </tr>
      `).join(""),
      1,
      "Las capas faltantes apareceran aqui."
    );

    renderNoteList("stagingWarningsList", warnings, "warn");
    renderNoteList("stagingErrorsList", errors, "error");
  }

  async function performStagingImport(mode, button) {
    if (!zipFileInput || !zipFileInput.files || !zipFileInput.files[0]) {
      setStatus(stagingStatus, "error", "Selecciona el archivo ZIP antes de ejecutar Fase 4.");
      return;
    }
    const targetSchema = String(schemaSelect.value || "").trim();
    if (!targetSchema) {
      setStatus(stagingStatus, "error", "Selecciona un schema destino antes de ejecutar Fase 4.");
      return;
    }
    const payload = buildPayload();
    if (!payload.host || !payload.user || !payload.database) {
      setStatus(stagingStatus, "error", "Completa y valida la conexion local antes de ejecutar Fase 4.");
      return;
    }
    const stagingSchema = String(stagingSchemaInput?.value || "").trim();
    if (!stagingSchema) {
      setStatus(stagingStatus, "error", "Define el schema temporal/staging.");
      return;
    }

    const originalLabel = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Ejecutando';
    setStatus(stagingStatus, "neutral", mode === "dry_run" ? "Simulando importacion a staging..." : "Importando a schema temporal...");

    const formData = new FormData();
    formData.append("zip_file", zipFileInput.files[0]);
    formData.append("host", payload.host);
    formData.append("port", String(payload.port));
    formData.append("user", payload.user);
    formData.append("password", payload.password);
    formData.append("database", payload.database);
    formData.append("target_schema", targetSchema);
    formData.append("staging_schema", stagingSchema);
    formData.append("mode", mode);
    formData.append("replace", replaceStagingCheckbox && replaceStagingCheckbox.checked ? "true" : "false");

    try {
      const data = await postFormData(`${window.rp}/api/sincronizacion-mergin/import-staging`, formData);
      renderStagingReport(data);
      setStatus(
        stagingStatus,
        data.ok ? "success" : "error",
        data.ok
          ? (mode === "dry_run" ? "Simulacion completada sin escritura en PostgreSQL." : "Importacion completada hacia el schema staging.")
          : ((data.errors && data.errors[0]) || "No fue posible completar la operacion de staging.")
      );
    } catch (error) {
      setStatus(stagingStatus, "error", error.message || "No fue posible ejecutar la operacion de staging.");
    } finally {
      button.disabled = false;
      button.innerHTML = originalLabel;
    }
  }

  connectionForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const payload = buildPayload();
    if (!payload.host || !payload.user || !payload.database || !Number.isFinite(payload.port) || payload.port < 1) {
      connectionState = null;
      setStatus(connectionStatus, "error", "Completa host, puerto, usuario y base de datos antes de probar la conexion.");
      setStatus(schemaStatus, "error", "No se puede continuar hasta validar la conexion local.");
      resetSchemaUi("Completa la conexion y la base de datos para listar schemas compatibles.");
      return;
    }

    btnTestConnection.disabled = true;
    btnTestConnection.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Probando conexion';
    setStatus(connectionStatus, "neutral", "Probando conexion contra PostgreSQL local...");
    setStatus(schemaStatus, "neutral", "Esperando una conexion valida para cargar el destino.");
    resetSchemaUi("Conecta una base local para listar schemas compatibles.");

    try {
      const data = await postJson(`${window.rp}/api/sincronizacion-mergin/test-connection`, payload);
      connectionState = payload;
      await loadSchemas(payload.database);
      setStatus(connectionStatus, "success", data.message || "Conexion exitosa.");
    } catch (error) {
      connectionState = null;
      setStatus(connectionStatus, "error", error.message || "No fue posible establecer conexion.");
      setStatus(schemaStatus, "error", "No se puede continuar hasta validar la conexion local.");
    } finally {
      btnTestConnection.disabled = false;
      btnTestConnection.innerHTML = '<i class="bi bi-plug-fill"></i> Probar conexion';
    }
  });

  schemaSelect.addEventListener("change", (event) => {
    const selected = String(event.target.value || "").trim();
    if (!selected) {
      setStatus(schemaStatus, "neutral", "Selecciona un schema destino.");
      return;
    }
    syncSuggestedStagingSchema(true);
    setStatus(schemaStatus, "success", `Schema destino seleccionado: ${selected}.`);
  });

  databaseInput.addEventListener("change", () => {
    syncSuggestedStagingSchema(false);
  });

  if (btnAnalyzeZip && zipFileInput && zipStatus) {
    btnAnalyzeZip.addEventListener("click", async () => {
      const file = zipFileInput.files && zipFileInput.files[0];
      if (!file) {
        setStatus(zipStatus, "error", "Selecciona un archivo ZIP antes de analizar.");
        return;
      }

      const formData = new FormData();
      formData.append("file", file);

      btnAnalyzeZip.disabled = true;
      btnAnalyzeZip.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Analizando';
      setStatus(zipStatus, "neutral", `Analizando ${file.name}...`);

      try {
        const data = await postFormData(`${window.rp}/api/sincronizacion-mergin/analyze-zip`, formData);
        renderZipAnalysis(data);
        setStatus(zipStatus, "success", `Analisis completado para ${data.zip_name || file.name}.`);
      } catch (error) {
        setStatus(zipStatus, "error", error.message || "No fue posible analizar el ZIP.");
      } finally {
        btnAnalyzeZip.disabled = false;
        btnAnalyzeZip.innerHTML = '<i class="bi bi-file-earmark-zip"></i> Analizar';
      }
    });
  }

  if (btnDryRunImport && stagingStatus) {
    btnDryRunImport.addEventListener("click", async () => {
      await performStagingImport("dry_run", btnDryRunImport);
    });
  }

  if (btnImportStaging && stagingStatus) {
    btnImportStaging.addEventListener("click", async () => {
      await performStagingImport("import", btnImportStaging);
    });
  }

  syncSuggestedStagingSchema(false);
})();
