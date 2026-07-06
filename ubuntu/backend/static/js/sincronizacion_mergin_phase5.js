(function () {
  const btnDryRunEtl = document.getElementById("btnDryRunEtl");
  const btnApplyEtl = document.getElementById("btnApplyEtl");
  const etlStatus = document.getElementById("etlStatus");
  const etlReportPanel = document.getElementById("etlReportPanel");
  const schemaSelect = document.getElementById("schemaSelect");
  const databaseInput = document.getElementById("database");
  const stagingSchemaInput = document.getElementById("stagingSchemaInput");
  const connectionForm = document.getElementById("merginConnectionForm");

  if (!btnDryRunEtl || !btnApplyEtl || !etlStatus || !schemaSelect || !databaseInput || !stagingSchemaInput || !connectionForm) {
    return;
  }

  function setStatus(element, kind, message) {
    element.className = `mergin-sync-status ${kind}`;
    element.textContent = message;
  }

  function setText(id, value, fallback = "0") {
    const element = document.getElementById(id);
    if (!element) {
      return;
    }
    element.textContent = value !== undefined && value !== null && value !== "" ? String(value) : fallback;
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
    const list = Array.isArray(items) ? items : [];
    element.innerHTML = list.map((item) => `<div class="mergin-sync-note ${kind}">${item}</div>`).join("");
  }

  function buildPayload(mode) {
    const formData = new FormData(connectionForm);
    return {
      host: String(formData.get("host") || "").trim(),
      port: Number(formData.get("port") || 5432),
      user: String(formData.get("user") || "").trim(),
      password: String(formData.get("password") || ""),
      database: String(databaseInput.value || "").trim(),
      staging_schema: String(stagingSchemaInput.value || "").trim(),
      target_schema: String(schemaSelect.value || "").trim(),
      mode,
    };
  }

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
    return parts.join(": ") || `HTTP ${response.status}`;
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

  function renderEtlReport(data) {
    if (!etlReportPanel) {
      return;
    }
    etlReportPanel.hidden = false;
    const summary = data.summary || {};
    const tables = Array.isArray(data.tables) ? data.tables : [];
    const excluded = Array.isArray(data.excluded_tables) ? data.excluded_tables : [];
    const stagingOnly = Array.isArray(data.staging_only_tables) ? data.staging_only_tables : [];
    const targetOnly = Array.isArray(data.target_only_tables) ? data.target_only_tables : [];
    const warnings = Array.isArray(data.warnings) ? data.warnings : [];
    const critical = Array.isArray(data.critical_errors) ? data.critical_errors : [];

    setText("etlMode", data.mode || "No ejecutado", "No ejecutado");
    setText("etlStagingSchema", data.staging_schema || "No definido", "No definido");
    setText("etlTargetSchema", data.target_schema || "No definido", "No definido");
    setText("etlSyncableTables", Number(summary.syncable_tables || 0).toLocaleString("es-CO"));
    setText("etlNonSyncableTables", Number(summary.nonsyncable_tables || 0).toLocaleString("es-CO"));
    setText("etlInsertEstimated", Number(summary.inserts_estimated || 0).toLocaleString("es-CO"));
    setText("etlUpdateEstimated", Number(summary.updates_estimated || 0).toLocaleString("es-CO"));
    setText("etlCriticalCount", Number(summary.critical_errors || 0).toLocaleString("es-CO"));
    setText("etlWarningsCount", Number(summary.warnings || 0).toLocaleString("es-CO"));
    setText("etlNonSyncableRecords", Number(summary.nonsyncable_records || 0).toLocaleString("es-CO"));
    setText("etlExcludedTables", Number(summary.excluded_tables || 0).toLocaleString("es-CO"));
    setText("etlStagingOnlyTables", Number(summary.staging_only_tables || 0).toLocaleString("es-CO"));
    setText("etlTargetOnlyTables", Number(summary.target_only_tables || 0).toLocaleString("es-CO"));

    renderRows(
      document.getElementById("etlTablesBody"),
      tables.map((table) => {
        const statusClass = table.syncable ? "ok" : "no";
        const keyLabel = table.key_column ? `${table.key_column} (${table.key_strategy || "manual"})` : "Sin llave";
        return `
          <tr>
            <td><strong>${table.table || "Sin nombre"}</strong></td>
            <td><span class="mergin-sync-pill ${statusClass}">${table.syncable ? "Sincronizable" : "Bloqueada"}</span></td>
            <td>${keyLabel}</td>
            <td>${Number(table.insertable_records || 0).toLocaleString("es-CO")}</td>
            <td>${Number(table.updatable_records || 0).toLocaleString("es-CO")}</td>
            <td>${Number(table.nonsyncable_records || 0).toLocaleString("es-CO")}</td>
          </tr>
        `;
      }).join(""),
      6,
      "El reporte ETL aparecera aqui."
    );

    renderRows(
      document.getElementById("etlExcludedBody"),
      excluded.map((item) => `
        <tr>
          <td><strong>${item.table || "Sin nombre"}</strong></td>
          <td>${item.reason || "Sin detalle"}</td>
          <td>${Number(item.staging_count || 0).toLocaleString("es-CO")}</td>
          <td>${Number(item.target_count || 0).toLocaleString("es-CO")}</td>
        </tr>
      `).join(""),
      4,
      "Las tablas excluidas apareceran aqui."
    );

    renderRows(
      document.getElementById("etlSchemaMismatchBody"),
      [...stagingOnly.map((item) => ({ ...item, location: "Solo en staging" })), ...targetOnly.map((item) => ({ ...item, location: "Solo en target" }))].map((item) => `
        <tr>
          <td><strong>${item.table || "Sin nombre"}</strong></td>
          <td>${item.location || "Sin detalle"}</td>
          <td>${item.reason || "Sin detalle"}</td>
          <td>${Number(item.staging_count || 0).toLocaleString("es-CO")}</td>
          <td>${Number(item.target_count || 0).toLocaleString("es-CO")}</td>
        </tr>
      `).join(""),
      5,
      "No se detectaron diferencias de presencia entre staging y target."
    );

    renderNoteList("etlWarningsList", warnings, "warn");
    renderNoteList("etlCriticalList", critical, "error");
  }

  async function executeEtl(mode, button) {
    const payload = buildPayload(mode);
    if (!payload.host || !payload.user || !payload.database) {
      setStatus(etlStatus, "error", "Completa y valida la conexion local antes de ejecutar Fase 5.");
      return;
    }
    if (!payload.target_schema) {
      setStatus(etlStatus, "error", "Selecciona el schema destino antes de ejecutar Fase 5.");
      return;
    }
    if (!payload.staging_schema) {
      setStatus(etlStatus, "error", "Define el schema staging antes de ejecutar Fase 5.");
      return;
    }

    const originalLabel = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Ejecutando';
    setStatus(etlStatus, "neutral", mode === "dry_run" ? "Simulando transferencia hacia target..." : "Aplicando transferencia hacia target...");

    try {
      const data = await postJson(`${window.rp}/api/sincronizacion-mergin/apply-etl`, payload);
      renderEtlReport(data);
      setStatus(etlStatus, data.ok ? "success" : "error", data.message || (data.ok ? "ETL completado." : "No fue posible completar el ETL."));
    } catch (error) {
      setStatus(etlStatus, "error", error.message || "No fue posible ejecutar el ETL.");
    } finally {
      button.disabled = false;
      button.innerHTML = originalLabel;
    }
  }

  btnDryRunEtl.addEventListener("click", async () => {
    await executeEtl("dry_run", btnDryRunEtl);
  });

  btnApplyEtl.addEventListener("click", async () => {
    await executeEtl("apply", btnApplyEtl);
  });
})();
