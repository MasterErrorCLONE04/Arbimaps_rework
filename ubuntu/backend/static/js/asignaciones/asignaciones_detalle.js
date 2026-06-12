// JS Bridge config for variables injected from Jinja2
const config = window.asignacionesConfig || {};
const rp = config.rp || "";
const currentLoggedUser = config.currentLoggedUser || "";
const currentLoggedRole = config.currentLoggedRole || "";
const asigSchemaWork = config.asigSchemaWork || {};
const ASSIGN_WMS_LAYER_DETAIL = config.assignWmsLayerDetail || "B_ASIGNACIONES_ARB:ASIGNACIONES";

let currentAssignmentData = null;

// Helper wrapper functions for SweetAlert2 styled alerts
function showAlert(title, text, icon = 'info') {
  Swal.fire({
    title: title,
    text: text,
    icon: icon,
    confirmButtonColor: '#032F57',
    confirmButtonText: 'Aceptar',
    customClass: {
      popup: 'rounded-4'
    }
  });
}

function showSuccess(text) {
  showAlert('¡Éxito!', text, 'success');
}

function showError(text) {
  showAlert('Error', text, 'error');
}

function showWarning(text) {
  showAlert('Atención', text, 'warning');
}

function showConfirm(title, text, confirmButtonText = 'Sí, continuar') {
  return Swal.fire({
    title: title,
    text: text,
    icon: 'question',
    showCancelButton: true,
    confirmButtonColor: '#22c55e',
    cancelButtonColor: '#94a3b8',
    confirmButtonText: confirmButtonText,
    cancelButtonText: 'Cancelar',
    customClass: {
      popup: 'rounded-4'
    }
  });
}

    $(document).ready(function () {
      $.fn.DataTable.ext.pager.numbers_length = 3;

      tablaPrediosDT = $('#tablaPredios').DataTable({
        pageLength: 5,
        lengthChange: false,
        ordering: true,
        searching: false,
        info: true,
        paging: true,
        pagingType: "simple_numbers",
        responsive: false,
        autoWidth: false,
        scrollX: true,
        language: {
          zeroRecords: "No se encontraron resultados",
          info: "Mostrando _START_ a _END_ de _TOTAL_ resultados",
          infoEmpty: "Mostrando 0 a 0 de 0 resultados",
          infoFiltered: "(filtrado de _MAX_ registros totales)",
          emptyTable: "Sin datos.",
          paginate: {
            next: "›",
            previous: "‹"
          }
        }
      });

      tablaPrediosDT.on("draw", syncPredioSelectionUI);

      tablaHistorialDT = $('#tablaHistorial').DataTable({
        ordering: true,
        searching: false,
        info: false,
        paging: false,
        responsive: false,
        autoWidth: false,
        scrollX: true,
        language: {
          zeroRecords: "No se encontraron resultados",
          emptyTable: "Sin datos."
        }
      });

      $('#modalHistorial').on('shown.bs.modal', function () {
        if (tablaHistorialDT) {
          tablaHistorialDT.columns.adjust().draw();
        }
      });
    });

const params = new URLSearchParams(window.location.search);
    const idFromUrl = params.get("id");
    let predioSeleccionadoDetalleId = null;
    let predioSeleccionadoTId = null;
    let predioSeleccionadoNumero = null;
    const fechaFmt = new Intl.DateTimeFormat("es-CO", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit"
    });

    const elId = document.getElementById("asigDetalleId");
    const msg = document.getElementById("asigDetailMsg");
    const prediosBody = document.getElementById("asigDetallePrediosBody");
    const eventosBody = document.getElementById("asigDetalleEventosBody");

    const fileInput = document.getElementById("asigRetornoFile");
    const xtfPreviewBox = document.getElementById("xtfPreviewBox");
    const xtfPreviewCheck = document.getElementById("xtfPreviewCheck");
    const xtfPreviewIcon = document.getElementById("xtfPreviewIcon");
    const xtfFileName = document.getElementById("xtfFileName");
    const xtfFileMeta = document.getElementById("xtfFileMeta");
    const btnRemoveXtf = document.getElementById("btnRemoveXtf");
    const btnImportarRetorno = document.getElementById("btnImportarRetorno");
    const btnVerValidadores = document.getElementById("btnVerValidadores");
    const modalValidadoresXtf = document.getElementById("modalValidadoresXtf");
    const validadoresXtfBody = document.getElementById("validadoresXtfBody");
    const btnRecargarValidadoresXtf = document.getElementById("btnRecargarValidadoresXtf");
    let retornoEnCurso = false;
    let validadoresCargados = false;

    function esc(value) {
      if (value === null || value === undefined) return "";
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function setText(id, value) {
      const el = document.getElementById(id);
      if (el) el.textContent = value ?? "-";
    }

    function syncPredioSelectionUI() {
      document.querySelectorAll("#asigDetallePrediosBody tr").forEach((row) => {
        const rowTId = row.getAttribute("data-predio-t-id");
        const isSelected = predioSeleccionadoTId !== null
          && String(rowTId) === String(predioSeleccionadoTId);
        row.classList.toggle("table-active", isSelected);
      });
    }

    function fmtDate(value) {
      if (!value) return "-";
      const d = new Date(value);
      if (Number.isNaN(d.getTime())) return String(value);
      return fechaFmt.format(d);
    }

    function formatFileSize(bytes) {
      if (!bytes || bytes <= 0) return "0 KB";
      const units = ["B", "KB", "MB", "GB"];
      let size = bytes;
      let unitIndex = 0;

      while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex++;
      }

      const decimals = unitIndex === 0 ? 0 : 2;
      return `${size.toFixed(decimals)} ${units[unitIndex]}`;
    }

    function renderXtfPreview(file) {
      if (!file) {
        xtfPreviewBox?.classList.add("d-none");
        if (xtfPreviewBox) delete xtfPreviewBox.dataset.fileSize;
        if (xtfFileName) xtfFileName.textContent = "";
        if (xtfFileMeta) xtfFileMeta.textContent = "";
        return;
      }

      if (xtfPreviewBox) xtfPreviewBox.dataset.fileSize = formatFileSize(file.size);
      if (xtfFileName) xtfFileName.textContent = file.name;
      xtfPreviewBox?.classList.remove("d-none");
      setXtfSyncState("pending");
    }

    function setXtfSyncState(state, detail = "") {
      if (!xtfPreviewBox || !xtfPreviewCheck || !xtfPreviewIcon || !xtfFileMeta) return;

      const base = xtfPreviewBox.dataset.fileSize || "0 KB";
      const suffix = detail ? ` | ${detail}` : "";
      xtfPreviewIcon.className = "";
      xtfPreviewCheck.style.background = "#ffffff";

      if (state === "syncing") {
        xtfPreviewIcon.className = "spinner-border spinner-border-sm";
        xtfPreviewCheck.style.borderColor = "#0b5ed7";
        xtfPreviewCheck.style.color = "#0b5ed7";
        xtfFileMeta.textContent = `${base} | sincronizando...${suffix}`;
        if (btnImportarRetorno) btnImportarRetorno.disabled = true;
        if (btnRemoveXtf) btnRemoveXtf.disabled = true;
        return;
      }

      if (state === "success") {
        xtfPreviewIcon.className = "bi bi-check-lg";
        xtfPreviewCheck.style.borderColor = "#22c55e";
        xtfPreviewCheck.style.color = "#22c55e";
        xtfFileMeta.textContent = `${base} | sincronizado${suffix}`;
        if (btnImportarRetorno) btnImportarRetorno.disabled = false;
        if (btnRemoveXtf) btnRemoveXtf.disabled = false;
        return;
      }

      if (state === "error") {
        xtfPreviewIcon.className = "bi bi-x-lg";
        xtfPreviewCheck.style.borderColor = "#dc3545";
        xtfPreviewCheck.style.color = "#dc3545";
        xtfFileMeta.textContent = `${base} | error de sincronizacion${suffix}`;
        if (btnImportarRetorno) btnImportarRetorno.disabled = false;
        if (btnRemoveXtf) btnRemoveXtf.disabled = false;
        return;
      }

      xtfPreviewIcon.className = "bi bi-clock-history";
      xtfPreviewCheck.style.borderColor = "#94a3b8";
      xtfPreviewCheck.style.color = "#64748b";
      xtfFileMeta.textContent = `${base} | listo para sincronizar${suffix}`;
      if (btnImportarRetorno) btnImportarRetorno.disabled = false;
      if (btnRemoveXtf) btnRemoveXtf.disabled = false;
    }

    function formatBackendDetail(detail) {
      if (!detail) return "";
      return String(detail)
        .replace(/^\[[^\]]+\]\s*/g, "")
        .replace(/\s+/g, " ")
        .trim();
    }

    function renderValidadoresXtf(data) {
      if (!validadoresXtfBody) return;
      const pipeline = Array.isArray(data?.pipeline) ? data.pipeline : [];
      const qualityRules = Array.isArray(data?.quality_rules) ? data.quality_rules : [];
      const ili = data?.ili2_validator || {};

      const pipelineHtml = pipeline.length
        ? `<ul class="mb-3">${pipeline.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>`
        : `<p class="mb-3 text-muted">No hay pipeline configurado.</p>`;

      const qualityHtml = qualityRules.length
        ? qualityRules.map((item) => {
          const rules = Array.isArray(item?.rules) ? item.rules : [];
          const rulesHtml = rules.length
            ? `<ul class="mb-2">${rules.map((r) => `<li><strong>${esc(r.rule_id || "-")}:</strong> ${esc(r.description || "-")}</li>`).join("")}</ul>`
            : `<p class="mb-2 text-muted">Sin reglas declaradas.</p>`;
          return `
          <div class="mb-3">
            <div><strong>${esc(item.component || "-")}</strong> (${Number(item.total_rules || 0)} reglas)</div>
            ${rulesHtml}
          </div>
        `;
        }).join("")
        : `<p class="mb-0 text-muted">No hay reglas internas configuradas.</p>`;

      validadoresXtfBody.innerHTML = `
      <div class="mb-3">
        <div><strong>Pipeline de validacion</strong></div>
        ${pipelineHtml}
      </div>
      <div class="mb-3">
        <div><strong>ili2 validator</strong></div>
        <ul class="mb-0">
          <li><strong>JAR:</strong> ${esc(ili.jar_path || "-")}</li>
          <li><strong>Modelos:</strong> ${esc(ili.models || "-")}</li>
          <li><strong>Model dir:</strong> ${esc(ili.model_dir || "-")}</li>
          <li><strong>Extra args:</strong> ${esc((ili.extra_args || []).join(" ") || "-")}</li>
        </ul>
      </div>
      <div>
        <div><strong>Reglas internas</strong></div>
        ${qualityHtml}
      </div>
    `;
    }

    async function cargarValidadoresXtf(force = false) {
      if (!validadoresXtfBody) return;
      if (validadoresCargados && !force) return;

      validadoresXtfBody.innerHTML = `<span class="text-muted">Cargando validadores...</span>`;
      const resp = await fetch(`${rp}/asignaciones/validadores-xtf`, {
        credentials: "same-origin",
        headers: { "Accept": "application/json" }
      });

      let data = {};
      try {
        data = await resp.json();
      } catch (_e) {
        data = {};
      }

      if (!resp.ok) {
        throw new Error(formatBackendDetail(data?.detail) || "No se pudieron cargar los validadores XTF.");
      }

      validadoresCargados = true;
      renderValidadoresXtf(data);
    }

    async function cargarDetalle() {
      if (!tablaPrediosDT || !tablaHistorialDT) {
        msg.textContent = "Inicializando tablas...";
        return;
      }
      const id = Number(elId.value);
      if (!id || id < 1) {
        msg.textContent = "Debes indicar un id valido.";
        return;
      }

      msg.textContent = "Cargando detalle...";
      predioSeleccionadoDetalleId = null;
      invalidarCachesDetalleAsignacion();

      // Reset coordinator avatar to default state
      const avatarImg = document.getElementById("d_coord_avatar");
      const avatarIcon = document.getElementById("d_coord_icon");
      const avatarContainer = document.getElementById("d_coord_avatar_container");
      if (avatarImg && avatarIcon && avatarContainer) {
        avatarImg.style.display = "none";
        avatarIcon.style.display = "block";
        avatarContainer.style.backgroundColor = "rgba(255, 255, 255, 0.15)";
        avatarContainer.style.border = "1.5px solid transparent";
      }

      tablaPrediosDT.clear().draw();
      tablaHistorialDT.clear().draw();

      try {
        const [respDet, respEvt] = await Promise.all([
          fetch(`${rp}/asignaciones/${encodeURIComponent(id)}/detalle`, { credentials: "same-origin" }),
          fetch(`${rp}/asignaciones/${encodeURIComponent(id)}/eventos`, { credentials: "same-origin" })
        ]);

        const dataDet = await respDet.json().catch(() => ({}));
        const dataEvt = await respEvt.json().catch(() => ([]));
        currentAssignmentData = dataDet;

        if (!respDet.ok) throw new Error(dataDet?.detail || "No se pudo cargar el detalle.");
        if (!respEvt.ok) throw new Error(dataEvt?.detail || "No se pudieron cargar los eventos.");

        setText("d_id", dataDet.id);
        setText("d_estado", dataDet.estado || "-");
        setText("d_fecha", fmtDate(dataDet.fecha_creacion));
        // Set coordinator name and dynamic avatar
        const coordStr = dataDet.coordinador || "";
        setText("d_coord", coordStr || "-");

        const avatarContainer = document.getElementById("d_coord_avatar_container");
        const avatarImg = document.getElementById("d_coord_avatar");
        const avatarIcon = document.getElementById("d_coord_icon");

        if (avatarContainer && avatarImg && avatarIcon) {
          const match = coordStr.match(/\(([^)]+)\)/);
          const username = match ? match[1] : "";

          if (username && username !== "-") {
            avatarImg.src = `https://api.dicebear.com/7.x/adventurer/svg?seed=${encodeURIComponent(username)}&backgroundColor=b6e3f4`;
            avatarImg.style.display = "block";
            avatarIcon.style.display = "none";
            avatarContainer.style.backgroundColor = "#b6e3f4";
            avatarContainer.style.border = "1.5px solid rgba(255, 255, 255, 0.8)";
          } else {
            avatarImg.style.display = "none";
            avatarIcon.style.display = "block";
            avatarContainer.style.backgroundColor = "rgba(255, 255, 255, 0.15)";
            avatarContainer.style.border = "1.5px solid transparent";
          }
        }
        setText("d_user", dataDet.usuario_asignado || "-");
        setText("d_titulo", dataDet.titulo || "-");
        setText("d_main", dataDet.datasetname_main || "-");
        setText("d_work", dataDet.work_datasetname || "-");
        setText("d_error", dataDet.error_msg || "-");
        setText("d_asig", dataDet.total_asignados ?? 0);
        setText("d_elim", dataDet.total_eliminados ?? 0);
        setText("d_new", dataDet.total_nuevos ?? 0);

        // 1. Mostrar/Ocultar botón de Enviar a Control de Calidad
        const btnSubmitQA = document.getElementById("btnHeaderSubmitQA");
        if (btnSubmitQA) {
          const isReconocedor = currentLoggedRole === "reconocedor";
          const isOwner = dataDet.usuario_asignado_username === currentLoggedUser;
          const isEnCampo = dataDet.estado === "EN_CAMPO" || dataDet.estado === "DEVUELTO_CAMPO";

          if (isReconocedor && isOwner && isEnCampo) {
            btnSubmitQA.classList.remove("d-none");
            btnSubmitQA.classList.add("d-inline-flex");
          } else {
            btnSubmitQA.classList.add("d-none");
            btnSubmitQA.classList.remove("d-inline-flex");
          }
        }

        // 1.1 Mostrar/Ocultar botón de Revisar Control de Calidad (para Coordinador/Admin)
        const btnQCReview = document.getElementById("btnHeaderQCReview");
        if (btnQCReview) {
          const isReviewerRole = currentLoggedRole === "coordinador" || currentLoggedRole === "admin" || currentLoggedRole === "lider_reconocimiento";
          const isUnderReview = dataDet.estado === "CONTROL_CALIDAD_1";

          if (isReviewerRole && isUnderReview) {
            btnQCReview.classList.remove("d-none");
            btnQCReview.classList.add("d-inline-flex");
          } else {
            btnQCReview.classList.add("d-none");
            btnQCReview.classList.remove("d-inline-flex");
          }
        }

        // 1.2 Mostrar/Ocultar botón de Enviar Enlace a Coordinador (para Soporte/Admin)
        const btnSubmitSoporteLink = document.getElementById("btnHeaderSubmitSoporteLink");
        if (btnSubmitSoporteLink) {
          const isSoporteOrAdmin = currentLoggedRole === "soporte" || currentLoggedRole === "admin";
          const isGeneracionXtf = dataDet.estado === "GENERACION_XTF_CAMPO";
          const hasNoSoporteLink = !dataDet.enlace_soporte;

          if (isSoporteOrAdmin && isGeneracionXtf && hasNoSoporteLink) {
            btnSubmitSoporteLink.classList.remove("d-none");
            btnSubmitSoporteLink.classList.add("d-inline-flex");
          } else {
            btnSubmitSoporteLink.classList.add("d-none");
            btnSubmitSoporteLink.classList.remove("d-inline-flex");
          }
        }

        // 1.3 Mostrar/Ocultar botón de Ver Enlace de Soporte (para Coordinador/Admin/Lider/Asignado)
        const btnViewSoporteLink = document.getElementById("btnHeaderViewSoporteLink");
        if (btnViewSoporteLink) {
          const isReviewerRole = currentLoggedRole === "coordinador" || currentLoggedRole === "admin" || currentLoggedRole === "lider_reconocimiento";
          const isAssignee = currentLoggedRole === "digitalizador" || currentLoggedRole === "reconocedor";
          const isOwner = dataDet.usuario_asignado_username === currentLoggedUser;

          const hasSoporteLink = !!dataDet.enlace_soporte;
          const isAllowedState = dataDet.estado === "GENERACION_XTF_CAMPO" ||
            dataDet.estado === "EN_DIGITALIZACION" ||
            dataDet.estado === "DEVUELTO_DIGITALIZACION" ||
            dataDet.estado === "DEVUELTO_A_DIGITALIZACION";

          const canView = hasSoporteLink && isAllowedState && (isReviewerRole || (isAssignee && isOwner));

          if (canView) {
            btnViewSoporteLink.classList.remove("d-none");
            btnViewSoporteLink.classList.add("d-inline-flex");
          } else {
            btnViewSoporteLink.classList.add("d-none");
            btnViewSoporteLink.classList.remove("d-inline-flex");
          }
        }

        // 1.4 Mostrar/Ocultar botón de Enviar a Control de Calidad 2 (para digitalizador/reconocedor dueño)
        const btnSubmitQA2 = document.getElementById("btnHeaderSubmitQA2");
        if (btnSubmitQA2) {
          const isAssignee = currentLoggedRole === "digitalizador" || currentLoggedRole === "reconocedor";
          const isOwner = dataDet.usuario_asignado_username === currentLoggedUser;
          const isEnDigitalizacion = dataDet.estado === "EN_DIGITALIZACION" ||
            dataDet.estado === "DEVUELTO_DIGITALIZACION" ||
            dataDet.estado === "DEVUELTO_A_DIGITALIZACION";

          if (isAssignee && isOwner && isEnDigitalizacion) {
            btnSubmitQA2.classList.remove("d-none");
            btnSubmitQA2.classList.add("d-inline-flex");
          } else {
            btnSubmitQA2.classList.add("d-none");
            btnSubmitQA2.classList.remove("d-inline-flex");
          }
        }

        // 1.5 Mostrar/Ocultar botón de Revisar Control de Calidad 2 (para Coordinador/Admin)
        const btnQCReview2 = document.getElementById("btnHeaderQCReview2");
        if (btnQCReview2) {
          const isReviewerRole = currentLoggedRole === "coordinador" || currentLoggedRole === "admin";
          const isUnderReview2 = dataDet.estado === "CONTROL_CALIDAD_2";

          if (isReviewerRole && isUnderReview2) {
            btnQCReview2.classList.remove("d-none");
            btnQCReview2.classList.add("d-inline-flex");
          } else {
            btnQCReview2.classList.add("d-none");
            btnQCReview2.classList.remove("d-inline-flex");
          }
        }

        // 1.6 Mostrar/Ocultar botón de Revisión de Líder (para Lider de Reconocimiento/Admin)
        const btnLiderReview = document.getElementById("btnHeaderLiderReview");
        if (btnLiderReview) {
          const isLiderOrAdmin = currentLoggedRole === "lider_reconocimiento" || currentLoggedRole === "admin";
          const isAprobacion = dataDet.estado === "EN_APROBACION";

          if (isLiderOrAdmin && isAprobacion) {
            btnLiderReview.classList.remove("d-none");
            btnLiderReview.classList.add("d-inline-flex");
          } else {
            btnLiderReview.classList.add("d-none");
            btnLiderReview.classList.remove("d-inline-flex");
          }
        }
        // 1.7 Mostrar/Ocultar botón de Ver Enlace de Digitalización (para Soporte/Coordinador/Admin/Lider)
        const btnViewDigitalizacionLink = document.getElementById("btnHeaderViewDigitalizacionLink");
        if (btnViewDigitalizacionLink) {
          const isAllowedRole = currentLoggedRole === "soporte" || currentLoggedRole === "coordinador" || currentLoggedRole === "admin" || currentLoggedRole === "lider_reconocimiento";
          const hasDigitalizacionLink = !!dataDet.enlace_digitalizacion;
          const isSyncState = dataDet.estado === "EN_SINCRONIZACION" || dataDet.estado === "SINCRONIZADO";

          if (isAllowedRole && hasDigitalizacionLink && isSyncState) {
            btnViewDigitalizacionLink.classList.remove("d-none");
            btnViewDigitalizacionLink.classList.add("d-inline-flex");
          } else {
            btnViewDigitalizacionLink.classList.add("d-none");
            btnViewDigitalizacionLink.classList.remove("d-inline-flex");
          }
        }

        // 1.8 Mostrar/Ocultar botón de Sincronizar XTF (para Soporte/Admin)
        const btnSyncXtf = document.getElementById("btnHeaderSyncXtf");
        if (btnSyncXtf) {
          const isAllowedSyncRole = currentLoggedRole === "soporte" || currentLoggedRole === "admin";
          const isSyncState = dataDet.estado === "EN_SINCRONIZACION";

          if (isAllowedSyncRole && isSyncState) {
            btnSyncXtf.classList.remove("d-none");
            btnSyncXtf.classList.add("d-inline-flex");
          } else {
            btnSyncXtf.classList.add("d-none");
            btnSyncXtf.classList.remove("d-inline-flex");
          }
        }

        // 2. Mostrar/Ocultar enlace de control de calidad
        const qaLinkRow = document.getElementById("d_qa_link_row");
        const qaLink = document.getElementById("d_qa_link");
        if (qaLinkRow && qaLink) {
          if (dataDet.enlace_control_calidad) {
            qaLink.href = dataDet.enlace_control_calidad;
            qaLink.textContent = dataDet.enlace_control_calidad;
            qaLinkRow.classList.remove("d-none");
          } else {
            qaLinkRow.classList.add("d-none");
          }
        }

        // 2.1 Mostrar/Ocultar enlace de devolución activo
        const devLinkRow = document.getElementById("d_devolucion_link_row");
        const devLink = document.getElementById("d_devolucion_link");
        if (devLinkRow && devLink) {
          if (dataDet.enlace_devolucion) {
            devLink.href = dataDet.enlace_devolucion;
            devLink.textContent = dataDet.enlace_devolucion;
            devLinkRow.classList.remove("d-none");
          } else {
            devLinkRow.classList.add("d-none");
          }
        }

        const eventos = Array.isArray(dataEvt) ? dataEvt : [];
        let lastSyncDate = "-";
        const syncEvents = eventos.filter(e =>
          e && (
            e.evento === "PUBLICACION_MAIN" ||
            e.evento === "CARGA_WORKSPACE" ||
            String(e.mensaje || "").startsWith("[PUBLICACION_MAIN]") ||
            String(e.mensaje || "").startsWith("[CARGA_WORKSPACE]")
          )
        );
        if (syncEvents.length > 0) {
          lastSyncDate = fmtDate(syncEvents[syncEvents.length - 1].creado_en);
        }
        setText("d_last_sync", lastSyncDate);

        const predios = Array.isArray(dataDet.predios) ? dataDet.predios : [];
        prediosAsignacionDataEdit = predios;
        tablaPrediosDT.clear();

        if (predios.length) {
          predios.forEach(p => {
            const rowNode = tablaPrediosDT.row.add([
              esc(p.numero_predial_nacional || ""),
              esc(p.predio_t_id ?? "-"),
              `<span class="chip ${p.activo ? "ok" : "off"}">${p.activo ? "Activo" : "Inactivo"}</span>`,
              esc(p.creado_por || "-")
            ]).node();
            if (rowNode) {
              $(rowNode).attr("data-predio-id", p.id ?? "");
              $(rowNode).attr("data-predio-t-id", p.predio_t_id ?? "");
              $(rowNode).attr("data-numero-predial", p.numero_predial_nacional || "");
              $(rowNode).css("cursor", "pointer");
            }
          });
        }

        tablaPrediosDT.draw();
        syncPredioSelectionUI();

        // Initialize map and load assignment scope on details page
        loadAssignmentScopeDetalle(id);

        // Auto-select the first predio in the list if available
        if (predios.length > 0) {
          const firstPredio = predios[0];
          setTimeout(() => {
            seleccionarPredioDetalle(firstPredio.id, firstPredio.predio_t_id, firstPredio.numero_predial_nacional);
          }, 100);
        }

        tablaHistorialDT.clear();

        if (eventos.length) {
          eventos.slice().reverse().forEach(e => {
            tablaHistorialDT.row.add([
              esc(fmtDate(e.creado_en)),
              esc(e.evento || "-"),
              esc(e.mensaje || "-")
            ]);
          });
        }

        tablaHistorialDT.draw();

        // Helpers to format role names and state names nicely
        function formatRoleName(role) {
          if (!role) return "";
          const rolesMap = {
            "admin": "Administrador",
            "coordinador": "Coordinador",
            "reconocedor": "Reconocedor",
            "digitalizador": "Digitalizador",
            "soporte": "Soporte",
            "consolidador": "Consolidador",
            "lider_reconocimiento": "Líder de Reconocimiento"
          };
          return rolesMap[role.toLowerCase()] || role;
        }

        function formatStateName(state) {
          if (!state) return "";
          return state
            .replace(/_/g, " ")
            .toLowerCase()
            .split(" ")
            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
            .join(" ");
        }

        // Render comments
        const comentarios = Array.isArray(dataDet.comentarios) ? dataDet.comentarios : [];
        const badgeComentariosCount = document.getElementById("badgeComentariosCount");
        const comentariosList = document.getElementById("comentariosList");
        const noComentariosMsg = document.getElementById("noComentariosMsg");

        if (badgeComentariosCount) {
          if (comentarios.length > 0) {
            badgeComentariosCount.textContent = comentarios.length;
            badgeComentariosCount.classList.remove("d-none");
          } else {
            badgeComentariosCount.classList.add("d-none");
            badgeComentariosCount.textContent = "0";
          }
        }

        if (comentariosList) {
          comentariosList.innerHTML = "";
          if (comentarios.length > 0) {
            if (noComentariosMsg) noComentariosMsg.style.display = "none";
            comentarios.forEach(c => {
              const dateStr = fmtDate(c.creado_en);
              const userEsc = esc(c.usuario || "Usuario");
              const roleFmt = formatRoleName(c.rol);
              const commentEsc = esc(c.comentario || "").replace(/\n/g, "<br>");
              
              let transitionHtml = "";
              if (c.estado_origen || c.estado_destino) {
                const orig = formatStateName(c.estado_origen);
                const dest = formatStateName(c.estado_destino);
                if (orig && dest && orig !== dest) {
                  transitionHtml = `
                    <div class="mt-2 d-flex align-items-center gap-1 flex-wrap" style="font-size: 0.75rem;">
                      <span class="badge text-secondary border border-secondary bg-transparent px-2 py-1">${orig}</span>
                      <i class="fa-solid fa-arrow-right-long text-muted mx-1"></i>
                      <span class="badge bg-secondary text-white px-2 py-1">${dest}</span>
                    </div>
                  `;
                } else if (dest) {
                  transitionHtml = `
                    <div class="mt-2" style="font-size: 0.75rem;">
                      <span class="badge bg-secondary text-white px-2 py-1">${dest}</span>
                    </div>
                  `;
                }
              }

              // Determine icon and color based on role
              let roleBadgeClass = "bg-light text-dark border";
              let avatarBg = "rgba(100, 116, 139, 0.1)";
              let avatarIcon = '<i class="fa-solid fa-user text-secondary"></i>';
              
              const lowerRole = (c.rol || "").toLowerCase();
              if (lowerRole === "admin") {
                roleBadgeClass = "bg-danger text-white";
                avatarBg = "rgba(220, 53, 69, 0.1)";
                avatarIcon = '<i class="fa-solid fa-user-shield text-danger"></i>';
              } else if (lowerRole === "coordinador") {
                roleBadgeClass = "bg-primary text-white";
                avatarBg = "rgba(13, 110, 253, 0.1)";
                avatarIcon = '<i class="fa-solid fa-user-tie text-primary"></i>';
              } else if (lowerRole === "lider_reconocimiento") {
                roleBadgeClass = "bg-warning text-dark";
                avatarBg = "rgba(255, 193, 7, 0.15)";
                avatarIcon = '<i class="fa-solid fa-user-check text-warning-emphasis"></i>';
              } else if (lowerRole === "reconocedor") {
                roleBadgeClass = "bg-info text-dark";
                avatarBg = "rgba(13, 202, 240, 0.1)";
                avatarIcon = '<i class="fa-solid fa-compass text-info-emphasis"></i>';
              } else if (lowerRole === "digitalizador") {
                roleBadgeClass = "bg-success text-white";
                avatarBg = "rgba(25, 135, 84, 0.1)";
                avatarIcon = '<i class="fa-solid fa-laptop-code text-success"></i>';
              }

              let attachmentHtml = "";
              if (c.enlace) {
                const linkEsc = esc(c.enlace);
                attachmentHtml = `
                  <div class="mt-2">
                    <a href="${linkEsc}" target="_blank" class="btn-attachment-link">
                      <i class="fa-solid fa-link"></i>
                      <span class="text-truncate" style="max-width: 250px;">${linkEsc}</span>
                      <i class="fa-solid fa-arrow-up-right-from-square ms-1" style="font-size: 0.75rem;"></i>
                    </a>
                  </div>
                `;
              }

              const commentItem = document.createElement("div");
              commentItem.className = "card border-0 rounded-4 shadow-sm p-3 position-relative hover-lift";
              commentItem.style.backgroundColor = "#ffffff";
              commentItem.style.border = "1px solid #e2e8f0";
              commentItem.style.transition = "transform 0.2s ease, box-shadow 0.2s ease";
              
              commentItem.innerHTML = `
                <div class="d-flex align-items-start gap-3">
                  <div class="rounded-circle d-flex align-items-center justify-content-center flex-shrink-0" 
                       style="width: 40px; height: 40px; background-color: ${avatarBg}; font-size: 1.1rem;">
                    ${avatarIcon}
                  </div>
                  <div class="flex-grow-1 min-w-0">
                    <div class="d-flex align-items-center justify-content-between gap-2 flex-wrap mb-1">
                      <div class="d-flex align-items-center gap-2">
                        <span class="fw-bold text-dark" style="font-size: 0.95rem;">${userEsc}</span>
                        <span class="badge ${roleBadgeClass}" style="font-size: 0.7rem; font-weight: 600;">${roleFmt}</span>
                      </div>
                      <span class="text-muted" style="font-size: 0.75rem;">${dateStr}</span>
                    </div>
                    <div class="text-secondary" style="font-size: 0.88rem; line-height: 1.5; white-space: pre-wrap; word-break: break-word;">${commentEsc}</div>
                    ${attachmentHtml}
                    ${transitionHtml}
                  </div>
                </div>
              `;
              
              commentItem.addEventListener("mouseenter", () => {
                commentItem.style.transform = "translateY(-2px)";
                commentItem.style.boxShadow = "0 8px 16px rgba(0,0,0,0.08)";
              });
              commentItem.addEventListener("mouseleave", () => {
                commentItem.style.transform = "none";
                commentItem.style.boxShadow = "0 2px 4px rgba(0,0,0,0.04)";
              });

              comentariosList.appendChild(commentItem);
            });
          } else {
            if (noComentariosMsg) noComentariosMsg.style.display = "block";
          }
        }

        const breadcrumbName = document.getElementById("breadcrumbAssignmentName");
        if (breadcrumbName) {
          breadcrumbName.textContent = dataDet.titulo || "";
        }

        const newUrl = new URL(window.location.href);
        newUrl.searchParams.set("id", String(id));
        history.replaceState({}, "", newUrl.toString());
        msg.textContent = "";
      } catch (err) {
        msg.textContent = err?.message || "Error cargando detalle.";
        prediosBody.innerHTML = '<tr><td colspan="4">Error cargando predios.</td></tr>';
        eventosBody.innerHTML = '<tr><td colspan="3">Error cargando eventos.</td></tr>';
        const breadcrumbName = document.getElementById("breadcrumbAssignmentName");
        if (breadcrumbName) breadcrumbName.textContent = "";
      }
    }

    async function importarRetorno() {
      if (retornoEnCurso) return;

      const id = Number(elId.value);
      if (!id || id < 1) {
        msg.textContent = "Debes indicar un id valido antes de importar.";
        return;
      }

      const file = fileInput?.files?.[0];
      if (!file) {
        msg.textContent = "Selecciona primero un archivo .xtf.";
        return;
      }

      const form = new FormData();
      form.append("archivo", file);
      msg.textContent = "Importando retorno XTF...";
      setXtfSyncState("syncing");
      retornoEnCurso = true;

      try {
        const resp = await fetch(`${rp}/asignaciones/${encodeURIComponent(id)}/retorno-xtf`, {
          method: "POST",
          body: form,
          credentials: "same-origin",
          headers: { "Accept": "application/json" }
        });

        const rawText = await resp.text().catch(() => "");
        let data = {};
        if (rawText) {
          try {
            data = JSON.parse(rawText);
          } catch (_e) {
            data = {};
          }
        }

        if (!resp.ok) {
          const detail = formatBackendDetail(data?.detail || rawText);
          const error = new Error(detail || "No se pudo importar el retorno XTF.");
          error.status = resp.status;
          error.detail = detail;
          error.data = data;
          error.rawText = rawText;
          throw error;
        }

        const rulesWithIssues = Array.isArray(data?.validation_summary?.rules_with_issues)
          ? data.validation_summary.rules_with_issues
          : [];
        const successSuffix = rulesWithIssues.length ? ` | reglas: ${rulesWithIssues.join(", ")}` : "";
        setXtfSyncState("success", successSuffix);
        msg.textContent = data?.message || "Retorno XTF importado.";
        invalidarCachesDetalleAsignacion();
        await cargarDetalle();
      } catch (err) {
        setXtfSyncState("error");
        const detail = formatBackendDetail(err?.detail || err?.message);
        msg.textContent = detail || "Error importando retorno XTF.";
        console.error("retorno-xtf error", {
          status: err?.status,
          detail: err?.detail || err?.message,
          data: err?.data,
          rawText: err?.rawText || ""
        });
      } finally {
        retornoEnCurso = false;
      }
    }

    fileInput?.addEventListener("change", (e) => {
      const file = e.target.files?.[0];

      if (!file) {
        renderXtfPreview(null);
        return;
      }

      const extensionValida = file.name.toLowerCase().endsWith(".xtf");
      if (!extensionValida) {
        msg.textContent = "El archivo seleccionado no es un .xtf valido.";
        fileInput.value = "";
        renderXtfPreview(null);
        return;
      }

      renderXtfPreview(file);
      msg.textContent = `Archivo seleccionado: ${file.name}`;
    });

    btnRemoveXtf?.addEventListener("click", () => {
      if (fileInput) fileInput.value = "";
      renderXtfPreview(null);
      msg.textContent = "Archivo XTF removido.";
    });

    btnVerValidadores?.addEventListener("click", async () => {
      try {
        await cargarValidadoresXtf(false);
        if (window.bootstrap && modalValidadoresXtf) {
          window.bootstrap.Modal.getOrCreateInstance(modalValidadoresXtf).show();
        }
      } catch (err) {
        msg.textContent = err?.message || "No se pudieron cargar los validadores XTF.";
      }
    });

    btnRecargarValidadoresXtf?.addEventListener("click", async () => {
      try {
        validadoresCargados = false;
        await cargarValidadoresXtf(true);
      } catch (err) {
        if (validadoresXtfBody) {
          validadoresXtfBody.innerHTML = `<span class="text-danger">${esc(err?.message || "No se pudieron cargar los validadores.")}</span>`;
        }
      }
    });



    $(document).on("click", ".btn-editar-predio", function (e) {
      e.preventDefault();
      const idActual = Number(elId?.value || idFromUrl);
      if (!idActual || idActual < 1) {
        msg.textContent = "Debes cargar primero una asignacion.";
        return;
      }

      const predioTId = $(this).data("predio-t-id");
      const predioId = $(this).data("predio-id");
      const numero = $(this).data("numero");

      const query = new URLSearchParams();
      query.set("id", String(idActual));
      query.set("subview", "editar_predio");
      query.set("predio_t_id", String(predioTId));

      if (predioId !== null && String(predioId).trim() !== "") {
        query.set("predio_id", String(predioId));
      }

      if (numero) {
        query.set("numero_predial_nacional", String(numero));
      }

      window.location.href = `${rp}/panel/asignaciones/edicion?${query.toString()}#asig-open`;
    });



    document.getElementById("btnCargarDetalle")?.addEventListener("click", cargarDetalle);

    // Submit QA button click opens the modal
    document.getElementById("btnHeaderSubmitQA")?.addEventListener("click", () => {
      const inpLink = document.getElementById("inpQALink");
      const errEl = document.getElementById("qaLinkError");
      const commentEl = document.getElementById("txtQAComment");
      if (inpLink) inpLink.value = "";
      if (errEl) errEl.classList.add("d-none");
      if (commentEl) commentEl.value = "";

      const modalEl = document.getElementById("modalSubmitQA");
      if (modalEl && window.bootstrap) {
        window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
      }
    });

    // Confirm button inside modal
    document.getElementById("btnConfirmSubmitQA")?.addEventListener("click", async () => {
      const idActual = Number(elId?.value || idFromUrl);
      if (!idActual || idActual < 1) {
        showWarning("Debes cargar primero una asignación.");
        return;
      }

      const inpLink = document.getElementById("inpQALink");
      const errEl = document.getElementById("qaLinkError");
      const linkVal = inpLink?.value?.trim() || "";
      const commentVal = document.getElementById("txtQAComment")?.value?.trim() || "";

      if (!linkVal || (!linkVal.startsWith("http://") && !linkVal.startsWith("https://"))) {
        if (errEl) {
          errEl.textContent = "Por favor ingresa un enlace válido (debe iniciar con http:// o https://).";
          errEl.classList.remove("d-none");
        }
        return;
      }

      if (errEl) errEl.classList.add("d-none");

      const btnConfirm = document.getElementById("btnConfirmSubmitQA");
      const btnCancel = document.querySelector("#modalSubmitQA .btn-close, #modalSubmitQA [data-bs-dismiss='modal']");
      if (btnConfirm) btnConfirm.disabled = true;
      if (btnCancel) btnCancel.disabled = true;

      try {
        const response = await fetch(`${rp}/api/workflow/asignaciones/${idActual}/submit-for-qa`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Accept": "application/json"
          },
          body: JSON.stringify({ enlace_control_calidad: linkVal, comentario: commentVal || null }),
          credentials: "same-origin"
        });

        const rawText = await response.text();
        let data = {};
        if (rawText) {
          try {
            data = JSON.parse(rawText);
          } catch (e) {
            data = {};
          }
        }

        if (!response.ok) {
          throw new Error(data?.detail || rawText || "Error al enviar a control de calidad.");
        }

        const modalEl = document.getElementById("modalSubmitQA");
        if (modalEl && window.bootstrap) {
          window.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
        }

        showSuccess("El trabajo ha sido enviado exitosamente a control de calidad.");
        invalidarCachesDetalleAsignacion();
        await cargarDetalle();
      } catch (err) {
        showError(err.message);
      } finally {
        if (btnConfirm) btnConfirm.disabled = false;
        if (btnCancel) btnCancel.disabled = false;
      }
    });

    // QC Review button click opens the review modal
    document.getElementById("btnHeaderQCReview")?.addEventListener("click", () => {
      const modalEl = document.getElementById("modalQCReview");
      const qcLinkEl = document.getElementById("qcReviewEvidenceLink");
      const commentEl = document.getElementById("txtQCReviewComment");
      if (commentEl) commentEl.value = "";

      const currentLink = currentAssignmentData?.enlace_control_calidad || "";
      if (qcLinkEl) {
        qcLinkEl.href = currentLink;
        qcLinkEl.textContent = currentLink || "Sin enlace de evidencia";
      }

      if (modalEl && window.bootstrap) {
        window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
      }
    });

    // Reusable Rejection modal helper variables and function
    let devolucionTargetAction = "";
    let devolucionParentModalId = "";

    function openDevolucionModal(targetAction, parentModalId, confirmMessage) {
      devolucionTargetAction = targetAction;
      devolucionParentModalId = parentModalId;
      
      const parentModalEl = document.getElementById(parentModalId);
      if (parentModalEl && window.bootstrap) {
        window.bootstrap.Modal.getOrCreateInstance(parentModalEl).hide();
      }

      // Reset the textarea and errors
      const txtComment = document.getElementById("txtDevolucionComment");
      if (txtComment) txtComment.value = "";
      document.getElementById("devolucionCommentError")?.classList.add("d-none");
      
      const txtLink = document.getElementById("txtDevolucionLink");
      if (txtLink) txtLink.value = "";
      
      // Update modal title
      const labelEl = document.getElementById("modalConfirmarDevolucionLabel")?.querySelector("span");
      if (labelEl) {
        labelEl.textContent = confirmMessage || "Confirmar Devolución";
      }

      const modalEl = document.getElementById("modalConfirmarDevolucion");
      if (modalEl && window.bootstrap) {
        window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
      }
    }

    // Reopen parent modal on cancel/dismiss
    document.getElementById("modalConfirmarDevolucion")?.addEventListener("hidden.bs.modal", () => {
      if (devolucionTargetAction && devolucionParentModalId) {
        const parentModalEl = document.getElementById(devolucionParentModalId);
        if (parentModalEl && window.bootstrap) {
          window.bootstrap.Modal.getOrCreateInstance(parentModalEl).show();
        }
      }
      devolucionTargetAction = "";
      devolucionParentModalId = "";
    });

    // Confirm Devolucion button click handler
    document.getElementById("btnConfirmDevolucion")?.addEventListener("click", async () => {
      const idActual = Number(elId?.value || idFromUrl);
      if (!idActual || idActual < 1) {
        showWarning("Debes cargar primero una asignación.");
        return;
      }

      const commentVal = document.getElementById("txtDevolucionComment")?.value?.trim() || "";
      if (!commentVal) {
        document.getElementById("devolucionCommentError")?.classList.remove("d-none");
        document.getElementById("txtDevolucionComment")?.focus();
        return;
      } else {
        document.getElementById("devolucionCommentError")?.classList.add("d-none");
      }

      const linkVal = document.getElementById("txtDevolucionLink")?.value?.trim() || "";

      const btnConfirm = document.getElementById("btnConfirmDevolucion");
      if (btnConfirm) btnConfirm.disabled = true;

      let url = "";
      let successMsg = "";

      if (devolucionTargetAction === "devolver-campo") {
        url = `${rp}/api/workflow/asignaciones/${idActual}/return-to-field`;
        successMsg = "La asignación ha sido devuelta exitosamente a campo.";
      } else if (devolucionTargetAction === "devolver-soporte") {
        url = `${rp}/api/workflow/asignaciones/${idActual}/return-to-support`;
        successMsg = "La asignación ha sido devuelta exitosamente a soporte.";
      } else if (devolucionTargetAction === "devolver-digitalizacion") {
        url = `${rp}/api/workflow/asignaciones/${idActual}/return-to-digitalization`;
        successMsg = "La asignación ha sido devuelta exitosamente a digitalización.";
      } else if (devolucionTargetAction === "devolver-digitalizacion-lider") {
        url = `${rp}/api/workflow/asignaciones/${idActual}/lider-reject`;
        successMsg = "La asignación ha sido devuelta exitosamente a digitalización por el líder.";
      } else {
        showError("Acción de devolución no válida.");
        if (btnConfirm) btnConfirm.disabled = false;
        return;
      }

      try {
        const response = await fetch(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Accept": "application/json"
          },
          body: JSON.stringify({ comentario: commentVal, enlace: linkVal }),
          credentials: "same-origin"
        });

        if (!response.ok) {
          const rawText = await response.text();
          let data = {};
          try { data = JSON.parse(rawText); } catch (e) { }
          throw new Error(data?.detail || rawText || "Error al realizar la devolución.");
        }

        devolucionTargetAction = "";
        devolucionParentModalId = "";

        const modalEl = document.getElementById("modalConfirmarDevolucion");
        if (modalEl && window.bootstrap) {
          window.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
        }

        showSuccess(successMsg);
        invalidarCachesDetalleAsignacion();
        await cargarDetalle();
      } catch (err) {
        showError(err.message);
      } finally {
        if (btnConfirm) btnConfirm.disabled = false;
      }
    });

    // Confirm Return to Field (Reject) button click inside coordinator modal
    document.getElementById("btnQCReject")?.addEventListener("click", () => {
      openDevolucionModal("devolver-campo", "modalQCReview", "Devolver a Campo");
    });

    // Confirm Approve button click inside coordinator modal
    document.getElementById("btnQCApprove")?.addEventListener("click", () => {
      const idActual = Number(elId?.value || idFromUrl);
      if (!idActual || idActual < 1) {
        showWarning("Debes cargar primero una asignación.");
        return;
      }

      showConfirm(
        "¿Confirmar Aprobación?",
        "¿Estás seguro de que deseas aprobar este trabajo y enviarlo a generación XTF?",
        "Sí, aprobar"
      ).then(async (result) => {
        if (!result.isConfirmed) return;

        const btnReject = document.getElementById("btnQCReject");
        const btnApprove = document.getElementById("btnQCApprove");
        const btnCancel = document.querySelector("#modalQCReview .btn-close, #modalQCReview [data-bs-dismiss='modal']");
        if (btnReject) btnReject.disabled = true;
        if (btnApprove) btnApprove.disabled = true;
        if (btnCancel) btnCancel.disabled = true;

        try {
          const response = await fetch(`${rp}/api/workflow/asignaciones/${idActual}/approve`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Accept": "application/json"
            },
            body: JSON.stringify({ comentario: null }),
            credentials: "same-origin"
          });

          const rawText = await response.text();
          let data = {};
          if (rawText) {
            try {
              data = JSON.parse(rawText);
            } catch (e) {
              data = {};
            }
          }

          if (!response.ok) {
            throw new Error(data?.detail || rawText || "Error al aprobar la asignación.");
          }

          const modalEl = document.getElementById("modalQCReview");
          if (modalEl && window.bootstrap) {
            window.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
          }

          showSuccess("El trabajo ha sido aprobado exitosamente y enviado a generación XTF.");
          invalidarCachesDetalleAsignacion();
          await cargarDetalle();
        } catch (err) {
          showError(err.message);
        } finally {
          if (btnReject) btnReject.disabled = false;
          if (btnApprove) btnApprove.disabled = false;
          if (btnCancel) btnCancel.disabled = false;
        }
      });
    });

    // Submit Soporte Link button click opens the submit modal
    document.getElementById("btnHeaderSubmitSoporteLink")?.addEventListener("click", () => {
      const inpLink = document.getElementById("inpSoporteLink");
      const errEl = document.getElementById("soporteLinkError");
      const commentEl = document.getElementById("txtSoporteLinkComment");
      if (inpLink) inpLink.value = "";
      if (errEl) errEl.classList.add("d-none");
      if (commentEl) commentEl.value = "";

      const modalEl = document.getElementById("modalSubmitSoporteLink");
      if (modalEl && window.bootstrap) {
        window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
      }
    });

    // Confirm button inside Submit Soporte Link modal
    document.getElementById("btnConfirmSubmitSoporteLink")?.addEventListener("click", async () => {
      const idActual = Number(elId?.value || idFromUrl);
      if (!idActual || idActual < 1) {
        showWarning("Debes cargar primero una asignación.");
        return;
      }

      const inpLink = document.getElementById("inpSoporteLink");
      const errEl = document.getElementById("soporteLinkError");
      const linkVal = inpLink?.value?.trim() || "";
      const commentVal = document.getElementById("txtSoporteLinkComment")?.value?.trim() || "";

      if (!linkVal || (!linkVal.startsWith("http://") && !linkVal.startsWith("https://"))) {
        if (errEl) {
          errEl.textContent = "Por favor ingresa un enlace válido (debe iniciar con http:// o https://).";
          errEl.classList.remove("d-none");
        }
        return;
      }

      if (errEl) errEl.classList.add("d-none");

      const btnConfirm = document.getElementById("btnConfirmSubmitSoporteLink");
      const btnCancel = document.querySelector("#modalSubmitSoporteLink .btn-close, #modalSubmitSoporteLink [data-bs-dismiss='modal']");
      if (btnConfirm) btnConfirm.disabled = true;
      if (btnCancel) btnCancel.disabled = true;

      try {
        const response = await fetch(`${rp}/api/workflow/asignaciones/${idActual}/submit-soporte-link`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Accept": "application/json"
          },
          body: JSON.stringify({ enlace_soporte: linkVal, comentario: commentVal || null }),
          credentials: "same-origin"
        });

        const rawText = await response.text();
        let data = {};
        if (rawText) {
          try {
            data = JSON.parse(rawText);
          } catch (e) {
            data = {};
          }
        }

        if (!response.ok) {
          throw new Error(data?.detail || rawText || "Error al enviar el enlace de soporte.");
        }

        const modalEl = document.getElementById("modalSubmitSoporteLink");
        if (modalEl && window.bootstrap) {
          window.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
        }

        showSuccess("El enlace de soporte ha sido enviado exitosamente al coordinador.");
        invalidarCachesDetalleAsignacion();
        await cargarDetalle();
      } catch (err) {
        showError(err.message);
      } finally {
        if (btnConfirm) btnConfirm.disabled = false;
        if (btnCancel) btnCancel.disabled = false;
      }
    });

    // View Soporte Link button click opens the view modal and resets its subviews
    document.getElementById("btnHeaderViewSoporteLink")?.addEventListener("click", () => {
      const modalEl = document.getElementById("modalViewSoporteLink");
      const linkEl = document.getElementById("viewSoporteEvidenceLink");
      const commentEl = document.getElementById("txtSoporteComment");
      if (commentEl) commentEl.value = "";

      const currentLink = currentAssignmentData?.enlace_soporte || "";
      if (linkEl) {
        linkEl.href = currentLink;
        linkEl.textContent = currentLink || "Sin enlace";
      }

      // Reset internal modal subviews to default state
      document.getElementById("selectDigitalizadorContainer")?.classList.add("d-none");
      document.getElementById("viewSoporteMainContent")?.classList.remove("d-none");
      document.getElementById("viewSoporteDefaultFooter")?.classList.remove("d-none");
      document.getElementById("viewSoporteSelectorFooter")?.classList.add("d-none");
      document.getElementById("digitalizadorSelectError")?.classList.add("d-none");

      // Show/Hide coordinator action buttons inside the footer
      const isReviewerRole = currentLoggedRole === "coordinador" || currentLoggedRole === "admin" || currentLoggedRole === "lider_reconocimiento";
      const isGeneracionXtfState = currentAssignmentData?.estado === "GENERACION_XTF_CAMPO";
      const coordActions = document.getElementById("viewSoporteCoordinatorActions");
      if (coordActions) {
        if (isReviewerRole && isGeneracionXtfState) {
          coordActions.classList.remove("d-none");
          coordActions.classList.add("d-flex");
        } else {
          coordActions.classList.add("d-none");
          coordActions.classList.remove("d-flex");
        }
      }

      const selectEl = document.getElementById("selectDigitalizador");
      if (selectEl) {
        selectEl.innerHTML = '<option value="" disabled selected>Selecciona un digitalizador...</option>';
      }

      if (modalEl && window.bootstrap) {
        window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
      }
    });

    // Devolver a Soporte action inside View Soporte modal
    document.getElementById("btnViewSoporteDevolver")?.addEventListener("click", () => {
      openDevolucionModal("devolver-soporte", "modalViewSoporteLink", "Devolver a Soporte");
    });

    // Integrar Digitalizador triggers subview inside View Soporte modal
    document.getElementById("btnViewSoporteIntegrarDigit")?.addEventListener("click", async () => {
      document.getElementById("viewSoporteMainContent")?.classList.add("d-none");
      document.getElementById("viewSoporteDefaultFooter")?.classList.add("d-none");
      document.getElementById("selectDigitalizadorContainer")?.classList.remove("d-none");
      document.getElementById("viewSoporteSelectorFooter")?.classList.remove("d-none");
      document.getElementById("digitalizadorSelectError")?.classList.add("d-none");

      const selectEl = document.getElementById("selectDigitalizador");
      if (selectEl) {
        selectEl.innerHTML = '<option value="" disabled selected>Cargando digitalizadores...</option>';
        try {
          const response = await fetch(`${rp}/asignaciones/usuarios-disponibles`, { credentials: "same-origin" });
          const users = await response.json().catch(() => []);
          if (response.ok && Array.isArray(users)) {
            const digitalizadores = users.filter(u => u.rol && u.rol.toLowerCase() === "digitalizador");
            selectEl.innerHTML = '<option value="" disabled selected>Selecciona un digitalizador...</option>';
            digitalizadores.forEach(u => {
              const opt = document.createElement("option");
              opt.value = String(u.id_global);
              opt.textContent = `${u.first_name || ""} ${u.last_name || ""} (${u.username})`;
              selectEl.appendChild(opt);
            });
          } else {
            selectEl.innerHTML = '<option value="" disabled selected>Error al cargar digitalizadores</option>';
          }
        } catch (err) {
          selectEl.innerHTML = '<option value="" disabled selected>Error al cargar digitalizadores</option>';
        }
      }
    });

    // Volver inside selector view
    document.getElementById("btnCancelIntegrarDigit")?.addEventListener("click", () => {
      document.getElementById("selectDigitalizadorContainer")?.classList.add("d-none");
      document.getElementById("viewSoporteSelectorFooter")?.classList.add("d-none");
      document.getElementById("viewSoporteMainContent")?.classList.remove("d-none");
      document.getElementById("viewSoporteDefaultFooter")?.classList.remove("d-none");
      document.getElementById("digitalizadorSelectError")?.classList.add("d-none");
    });

    // Confirm digitalizador assignment
    document.getElementById("btnConfirmIntegrarDigit")?.addEventListener("click", async () => {
      const idActual = Number(elId?.value || idFromUrl);
      if (!idActual || idActual < 1) {
        showWarning("Debes cargar primero una asignación.");
        return;
      }

      const selectEl = document.getElementById("selectDigitalizador");
      const selectedId = selectEl?.value;
      const errEl = document.getElementById("digitalizadorSelectError");

      if (!selectedId) {
        if (errEl) errEl.classList.remove("d-none");
        return;
      }
      if (errEl) errEl.classList.add("d-none");

      const btnConfirm = document.getElementById("btnConfirmIntegrarDigit");
      const btnCancel = document.getElementById("btnCancelIntegrarDigit");
      if (btnConfirm) btnConfirm.disabled = true;
      if (btnCancel) btnCancel.disabled = true;

      try {
        const response = await fetch(`${rp}/api/workflow/asignaciones/${idActual}/assign-digitalizador`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Accept": "application/json"
          },
          body: JSON.stringify({ digitalizador_id: selectedId, comentario: null }),
          credentials: "same-origin"
        });

        if (!response.ok) {
          const rawText = await response.text();
          let data = {};
          try { data = JSON.parse(rawText); } catch (e) { }
          throw new Error(data?.detail || rawText || "Error al asignar digitalizador.");
        }

        const modalEl = document.getElementById("modalViewSoporteLink");
        if (modalEl && window.bootstrap) {
          window.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
        }

        showSuccess("Se ha integrado el digitalizador al trabajo exitosamente.");
        invalidarCachesDetalleAsignacion();
        await cargarDetalle();
      } catch (err) {
        showError(err.message);
      } finally {
        if (btnConfirm) btnConfirm.disabled = false;
        if (btnCancel) btnCancel.disabled = false;
      }
    });

    // Continuar con Reconocedor action inside View Soporte modal
    document.getElementById("btnViewSoporteContinuarRecon")?.addEventListener("click", () => {
      const idActual = Number(elId?.value || idFromUrl);
      if (!idActual || idActual < 1) {
        showWarning("Debes cargar primero una asignación.");
        return;
      }

      showConfirm(
        "¿Continuar con Reconocedor?",
        "¿Estás seguro de que deseas continuar con el mismo reconocedor para digitalización?",
        "Sí, continuar"
      ).then(async (result) => {
        if (!result.isConfirmed) return;

        const btnDevolver = document.getElementById("btnViewSoporteDevolver");
        const btnIntegrar = document.getElementById("btnViewSoporteIntegrarDigit");
        const btnContinuar = document.getElementById("btnViewSoporteContinuarRecon");
        if (btnDevolver) btnDevolver.disabled = true;
        if (btnIntegrar) btnIntegrar.disabled = true;
        if (btnContinuar) btnContinuar.disabled = true;

        try {
          const response = await fetch(`${rp}/api/workflow/asignaciones/${idActual}/continue-with-reconocedor`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Accept": "application/json"
            },
            body: JSON.stringify({ comentario: null }),
            credentials: "same-origin"
          });

          if (!response.ok) {
            const rawText = await response.text();
            let data = {};
            try { data = JSON.parse(rawText); } catch (e) { }
            throw new Error(data?.detail || rawText || "Error al continuar con reconocedor.");
          }

          const modalEl = document.getElementById("modalViewSoporteLink");
          if (modalEl && window.bootstrap) {
            window.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
          }

          showSuccess("Se ha continuado el trabajo con el reconocedor exitosamente.");
          invalidarCachesDetalleAsignacion();
          await cargarDetalle();
        } catch (err) {
          showError(err.message);
        } finally {
          if (btnDevolver) btnDevolver.disabled = false;
          if (btnIntegrar) btnIntegrar.disabled = false;
          if (btnContinuar) btnContinuar.disabled = false;
        }
      });
    });

    // Submit QA2 button click opens the submit QA2 modal
    document.getElementById("btnHeaderSubmitQA2")?.addEventListener("click", () => {
      const inpLink = document.getElementById("inpQA2Link");
      const errEl = document.getElementById("qa2LinkError");
      const commentEl = document.getElementById("txtQA2Comment");
      if (inpLink) inpLink.value = "";
      if (errEl) errEl.classList.add("d-none");
      if (commentEl) commentEl.value = "";

      const supportLink = currentAssignmentData?.enlace_soporte || "";
      const supportContainer = document.getElementById("qa2SoporteLinkContainer");
      const supportLinkEl = document.getElementById("qa2SoporteEvidenceLink");
      if (supportContainer && supportLinkEl) {
        if (supportLink) {
          supportLinkEl.href = supportLink;
          supportLinkEl.textContent = supportLink;
          supportContainer.classList.remove("d-none");
        } else {
          supportContainer.classList.add("d-none");
        }
      }

      const modalEl = document.getElementById("modalSubmitQA2");
      if (modalEl && window.bootstrap) {
        window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
      }
    });

    // Confirm button inside Submit QA2 modal
    document.getElementById("btnConfirmSubmitQA2")?.addEventListener("click", async () => {
      const idActual = Number(elId?.value || idFromUrl);
      if (!idActual || idActual < 1) {
        showWarning("Debes cargar primero una asignación.");
        return;
      }

      const inpLink = document.getElementById("inpQA2Link");
      const errEl = document.getElementById("qa2LinkError");
      const linkVal = inpLink?.value?.trim() || "";
      const commentVal = document.getElementById("txtQA2Comment")?.value?.trim() || "";

      if (!linkVal || (!linkVal.startsWith("http://") && !linkVal.startsWith("https://"))) {
        if (errEl) {
          errEl.textContent = "Por favor ingresa un enlace válido (debe iniciar con http:// o https://).";
          errEl.classList.remove("d-none");
        }
        return;
      }

      if (errEl) errEl.classList.add("d-none");

      const btnConfirm = document.getElementById("btnConfirmSubmitQA2");
      const btnCancel = document.querySelector("#modalSubmitQA2 .btn-close, #modalSubmitQA2 [data-bs-dismiss='modal']");
      if (btnConfirm) btnConfirm.disabled = true;
      if (btnCancel) btnCancel.disabled = true;

      try {
        const response = await fetch(`${rp}/api/workflow/asignaciones/${idActual}/submit-for-qa2`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Accept": "application/json"
          },
          body: JSON.stringify({ enlace_digitalizacion: linkVal, comentario: commentVal || null }),
          credentials: "same-origin"
        });

        if (!response.ok) {
          const rawText = await response.text();
          let data = {};
          try { data = JSON.parse(rawText); } catch (e) { }
          throw new Error(data?.detail || rawText || "Error al enviar a control de calidad 2.");
        }

        const modalEl = document.getElementById("modalSubmitQA2");
        if (modalEl && window.bootstrap) {
          window.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
        }

        showSuccess("El trabajo de digitalización ha sido enviado exitosamente a control de calidad 2.");
        invalidarCachesDetalleAsignacion();
        await cargarDetalle();
      } catch (err) {
        showError(err.message);
      } finally {
        if (btnConfirm) btnConfirm.disabled = false;
        if (btnCancel) btnCancel.disabled = false;
      }
    });

    // QC Review 2 button click opens the review modal
    document.getElementById("btnHeaderQCReview2")?.addEventListener("click", () => {
      const modalEl = document.getElementById("modalQCReview2");
      const qcLinkEl = document.getElementById("qcReview2EvidenceLink");
      const commentEl = document.getElementById("txtQC2ReviewComment");
      if (commentEl) commentEl.value = "";

      const currentLink = currentAssignmentData?.enlace_digitalizacion || "";
      if (qcLinkEl) {
        qcLinkEl.href = currentLink;
        qcLinkEl.textContent = currentLink || "Sin enlace de evidencia";
      }

      if (modalEl && window.bootstrap) {
        window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
      }
    });

    // Confirm Return to Digitalization (Reject) button click inside coordinator modal
    document.getElementById("btnQC2Reject")?.addEventListener("click", () => {
      openDevolucionModal("devolver-digitalizacion", "modalQCReview2", "Devolver a Digitalización");
    });

    // Confirm Approve Digitalization button click inside coordinator modal
    document.getElementById("btnQC2Approve")?.addEventListener("click", () => {
      const idActual = Number(elId?.value || idFromUrl);
      if (!idActual || idActual < 1) {
        showWarning("Debes cargar primero una asignación.");
        return;
      }

      showConfirm(
        "¿Confirmar Aprobación?",
        "¿Estás seguro de que deseas aprobar este trabajo de digitalización?",
        "Sí, aprobar"
      ).then(async (result) => {
        if (!result.isConfirmed) return;

        const btnReject = document.getElementById("btnQC2Reject");
        const btnApprove = document.getElementById("btnQC2Approve");
        const btnCancel = document.querySelector("#modalQCReview2 .btn-close, #modalQCReview2 [data-bs-dismiss='modal']");
        if (btnReject) btnReject.disabled = true;
        if (btnApprove) btnApprove.disabled = true;
        if (btnCancel) btnCancel.disabled = true;

        try {
          const response = await fetch(`${rp}/api/workflow/asignaciones/${idActual}/approve-digitalization`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Accept": "application/json"
            },
            body: JSON.stringify({ comentario: null }),
            credentials: "same-origin"
          });

          if (!response.ok) {
            const rawText = await response.text();
            let data = {};
            try { data = JSON.parse(rawText); } catch (e) { }
            throw new Error(data?.detail || rawText || "Error al aprobar digitalización.");
          }

          const modalEl = document.getElementById("modalQCReview2");
          if (modalEl && window.bootstrap) {
            window.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
          }

          showSuccess("El trabajo de digitalización ha sido aprobado exitosamente.");
          invalidarCachesDetalleAsignacion();
          await cargarDetalle();
        } catch (err) {
          showError(err.message);
        } finally {
          if (btnReject) btnReject.disabled = false;
          if (btnApprove) btnApprove.disabled = false;
          if (btnCancel) btnCancel.disabled = false;
        }
      });
    });

    // Leader Review button click opens the review modal
    document.getElementById("btnHeaderLiderReview")?.addEventListener("click", () => {
      const modalEl = document.getElementById("modalLiderReview");
      const qcLinkEl = document.getElementById("liderReviewEvidenceLink");
      const commentEl = document.getElementById("txtLiderReviewComment");
      if (commentEl) commentEl.value = "";

      const currentLink = currentAssignmentData?.enlace_digitalizacion || "";
      if (qcLinkEl) {
        qcLinkEl.href = currentLink;
        qcLinkEl.textContent = currentLink || "Sin enlace de evidencia";
      }

      if (modalEl && window.bootstrap) {
        window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
      }
    });

    // View Digitalizacion Link button click opens the view modal
    document.getElementById("btnHeaderViewDigitalizacionLink")?.addEventListener("click", () => {
      const modalEl = document.getElementById("modalViewDigitalizacionLink");
      const linkEl = document.getElementById("viewDigitalizacionEvidenceLink");

      const currentLink = currentAssignmentData?.enlace_digitalizacion || "";
      if (linkEl) {
        linkEl.href = currentLink;
        linkEl.textContent = currentLink || "Sin enlace de digitalización";
      }

      if (modalEl && window.bootstrap) {
        window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
      }
    });

    // Confirm Return to Digitalization (Reject) button click inside leader modal
    document.getElementById("btnLiderReject")?.addEventListener("click", () => {
      openDevolucionModal("devolver-digitalizacion-lider", "modalLiderReview", "Devolver a Digitalización");
    });

    // Confirm Approve Digitalization button click inside leader modal
    document.getElementById("btnLiderApprove")?.addEventListener("click", () => {
      const idActual = Number(elId?.value || idFromUrl);
      if (!idActual || idActual < 1) {
        showWarning("Debes cargar primero una asignación.");
        return;
      }

      showConfirm(
        "¿Confirmar Aprobación?",
        "¿Estás seguro de que deseas aprobar este trabajo de digitalización y comenzar la sincronización?",
        "Sí, aprobar y sincronizar"
      ).then(async (result) => {
        if (!result.isConfirmed) return;

        const btnReject = document.getElementById("btnLiderReject");
        const btnApprove = document.getElementById("btnLiderApprove");
        const btnCancel = document.querySelector("#modalLiderReview .btn-close, #modalLiderReview [data-bs-dismiss='modal']");
        if (btnReject) btnReject.disabled = true;
        if (btnApprove) btnApprove.disabled = true;
        if (btnCancel) btnCancel.disabled = true;

        try {
          const response = await fetch(`${rp}/api/workflow/asignaciones/${idActual}/lider-approve`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Accept": "application/json"
            },
            body: JSON.stringify({ comentario: null }),
            credentials: "same-origin"
          });

          if (!response.ok) {
            const rawText = await response.text();
            let data = {};
            try { data = JSON.parse(rawText); } catch (e) { }
            throw new Error(data?.detail || rawText || "Error al aprobar digitalización.");
          }

          const modalEl = document.getElementById("modalLiderReview");
          if (modalEl && window.bootstrap) {
            window.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
          }

          showSuccess("El trabajo de digitalización ha sido aprobado exitosamente y pasará a sincronización.");
          invalidarCachesDetalleAsignacion();
          await cargarDetalle();
        } catch (err) {
          showError(err.message);
        } finally {
          if (btnReject) btnReject.disabled = false;
          if (btnApprove) btnApprove.disabled = false;
          if (btnCancel) btnCancel.disabled = false;
        }
      });
    });

    btnImportarRetorno?.addEventListener("click", importarRetorno);

    document.getElementById("btnResetSearch")?.addEventListener("click", () => {
      window.location.href = `${rp}/panel/asignaciones/ver#asig-open`;
    });

    // Modal Sincronizar XTF bindings and logic
    const modalSincronizarXtf = document.getElementById("modalSincronizarXtf");
    const modalSyncAsigName = document.getElementById("modalSyncAsigName");
    const modalXtfFileInput = document.getElementById("modalXtfFileInput");
    const modalXtfPreviewBox = document.getElementById("modalXtfPreviewBox");
    const modalXtfFileName = document.getElementById("modalXtfFileName");
    const modalXtfFileMeta = document.getElementById("modalXtfFileMeta");
    const syncDragDropZone = document.getElementById("syncDragDropZone");
    const btnTriggerFileSelect = document.getElementById("btnTriggerFileSelect");
    const btnRemoveModalXtf = document.getElementById("btnRemoveModalXtf");
    const btnSubmitSyncModal = document.getElementById("btnSubmitSyncModal");
    const btnCancelSyncModal = document.getElementById("btnCancelSyncModal");

    const step1Item = document.getElementById("step1Item");
    const step2Item = document.getElementById("step2Item");
    const step3Item = document.getElementById("step3Item");
    const stepLine1 = document.getElementById("stepLine1");
    const stepLine2 = document.getElementById("stepLine2");

    const syncStep1Content = document.getElementById("syncStep1Content");
    const syncStep2Content = document.getElementById("syncStep2Content");
    const syncStep3Content = document.getElementById("syncStep3Content");

    const syncResultSuccessState = document.getElementById("syncResultSuccessState");
    const syncResultErrorState = document.getElementById("syncResultErrorState");
    const syncSuccessMessage = document.getElementById("syncSuccessMessage");
    const syncErrorMessage = document.getElementById("syncErrorMessage");

    let selectedModalFile = null;

    function resetModalSyncState() {
      selectedModalFile = null;
      if (modalXtfFileInput) modalXtfFileInput.value = "";

      // Reset Stepper items
      step1Item?.classList.add("active");
      step2Item?.classList.remove("active");
      step3Item?.classList.remove("active");
      stepLine1?.classList.remove("active");
      stepLine2?.classList.remove("active");

      // Reset Step contents
      syncStep1Content?.classList.remove("d-none");
      syncStep2Content?.classList.add("d-none");
      syncStep3Content?.classList.add("d-none");

      // Reset Result states
      syncResultSuccessState?.classList.add("d-none");
      syncResultErrorState?.classList.add("d-none");

      // Reset File zone
      syncDragDropZone?.classList.remove("d-none");
      modalXtfPreviewBox?.classList.add("d-none");

      // Reset buttons
      if (btnCancelSyncModal) {
        btnCancelSyncModal.disabled = false;
        btnCancelSyncModal.textContent = "Cancelar";
        btnCancelSyncModal.classList.remove("d-none");
      }
      btnSubmitSyncModal?.classList.add("d-none");
    }

    function displayModalFilePreview(file) {
      if (!file) {
        modalXtfPreviewBox?.classList.add("d-none");
        syncDragDropZone?.classList.remove("d-none");
        btnSubmitSyncModal?.classList.add("d-none");
        return;
      }

      if (modalXtfFileName) modalXtfFileName.textContent = file.name;
      if (modalXtfFileMeta) modalXtfFileMeta.textContent = formatFileSize(file.size);

      modalXtfPreviewBox?.classList.remove("d-none");
      btnSubmitSyncModal?.classList.remove("d-none");
    }

    async function submitSyncModalFile() {
      if (retornoEnCurso || !selectedModalFile) return;

      const id = Number(elId.value);
      if (!id || id < 1) {
        showWarning("Debes indicar un id válido.");
        return;
      }

      // Go to step 2 (Procesando)
      syncStep1Content?.classList.add("d-none");
      syncStep2Content?.classList.remove("d-none");

      step2Item?.classList.add("active");
      stepLine1?.classList.add("active");

      if (btnCancelSyncModal) {
        btnCancelSyncModal.disabled = true;
      }
      btnSubmitSyncModal?.classList.add("d-none");
      retornoEnCurso = true;

      const form = new FormData();
      form.append("archivo", selectedModalFile);

      try {
        const resp = await fetch(`${rp}/asignaciones/${encodeURIComponent(id)}/retorno-xtf`, {
          method: "POST",
          body: form,
          credentials: "same-origin",
          headers: { "Accept": "application/json" }
        });

        const rawText = await resp.text().catch(() => "");
        let data = {};
        if (rawText) {
          try {
            data = JSON.parse(rawText);
          } catch (_e) {
            data = {};
          }
        }

        // Go to step 3 (Resultado)
        syncStep2Content?.classList.add("d-none");
        syncStep3Content?.classList.remove("d-none");
        step3Item?.classList.add("active");
        stepLine2?.classList.add("active");

        if (btnCancelSyncModal) {
          btnCancelSyncModal.disabled = false;
          btnCancelSyncModal.textContent = "Finalizar";
        }

        if (!resp.ok) {
          const detail = formatBackendDetail(data?.detail || rawText);
          throw new Error(detail || "No se pudo importar el retorno XTF.");
        }

        // Show Success State
        syncResultSuccessState?.classList.remove("d-none");
        if (syncSuccessMessage) {
          const rulesWithIssues = Array.isArray(data?.validation_summary?.rules_with_issues)
            ? data.validation_summary.rules_with_issues
            : [];
          const successSuffix = rulesWithIssues.length ? ` (Reglas con observaciones: ${rulesWithIssues.join(", ")})` : "";
          syncSuccessMessage.textContent = (data?.message || "El archivo XTF se ha sincronizado correctamente.") + successSuffix;
        }

        // Reload parent detail page
        invalidarCachesDetalleAsignacion();
        await cargarDetalle();

      } catch (err) {
        // Show Error State
        syncResultErrorState?.classList.remove("d-none");
        if (syncErrorMessage) {
          syncErrorMessage.textContent = formatBackendDetail(err?.message || "Error al procesar el archivo XTF.");
        }
        if (btnCancelSyncModal) {
          btnCancelSyncModal.textContent = "Cerrar";
        }
      } finally {
        retornoEnCurso = false;
      }
    }

    // Drag and Drop
    syncDragDropZone?.addEventListener("dragover", (e) => {
      e.preventDefault();
      syncDragDropZone.classList.add("dragover");
    });

    syncDragDropZone?.addEventListener("dragenter", (e) => {
      e.preventDefault();
      syncDragDropZone.classList.add("dragover");
    });

    syncDragDropZone?.addEventListener("dragleave", (e) => {
      e.preventDefault();
      syncDragDropZone.classList.remove("dragover");
    });

    syncDragDropZone?.addEventListener("dragend", (e) => {
      e.preventDefault();
      syncDragDropZone.classList.remove("dragover");
    });

    syncDragDropZone?.addEventListener("drop", (e) => {
      e.preventDefault();
      syncDragDropZone.classList.remove("dragover");

      const file = e.dataTransfer?.files?.[0];
      if (file) {
        const extensionValida = file.name.toLowerCase().endsWith(".xtf");
        if (!extensionValida) {
          showWarning("El archivo seleccionado no es un .xtf válido.");
          return;
        }
        selectedModalFile = file;
        displayModalFilePreview(file);
      }
    });

    btnTriggerFileSelect?.addEventListener("click", () => {
      modalXtfFileInput?.click();
    });

    modalXtfFileInput?.addEventListener("change", (e) => {
      const file = e.target.files?.[0];
      if (file) {
        const extensionValida = file.name.toLowerCase().endsWith(".xtf");
        if (!extensionValida) {
          showWarning("El archivo seleccionado no es un .xtf válido.");
          modalXtfFileInput.value = "";
          return;
        }
        selectedModalFile = file;
        displayModalFilePreview(file);
      }
    });

    btnRemoveModalXtf?.addEventListener("click", () => {
      selectedModalFile = null;
      if (modalXtfFileInput) modalXtfFileInput.value = "";
      displayModalFilePreview(null);
    });

    btnSubmitSyncModal?.addEventListener("click", submitSyncModalFile);

    modalSincronizarXtf?.addEventListener("hidden.bs.modal", () => {
      resetModalSyncState();
    });

    document.getElementById("btnHeaderSyncXtf")?.addEventListener("click", () => {
      if (window.bootstrap && modalSincronizarXtf) {
        const asigTitle = document.getElementById("d_titulo")?.textContent || "-";
        if (modalSyncAsigName) {
          modalSyncAsigName.textContent = asigTitle;
        }
        resetModalSyncState();
        window.bootstrap.Modal.getOrCreateInstance(modalSincronizarXtf).show();
      }
    });


    $(document).ready(function () {
      if (idFromUrl && /^\d+$/.test(idFromUrl)) {
        if (elId) elId.value = idFromUrl;
        cargarDetalle();
      } else {
        window.location.href = `${rp}/panel/asignaciones/ver#asig-open`;
      }
    });

    // Attach row click listeners for the breakdown table to select predio
    $(document).on("click", "#tablaPredios tbody tr", function (e) {
      if ($(e.target).closest('.btn-editar-predio').length) {
        return; // Do not intercept clicks on the edit button
      }
      const predioTId = $(this).attr("data-predio-t-id");
      const predioId = $(this).attr("data-predio-id");
      const numero = $(this).attr("data-numero-predial");

      if (predioTId) {
        seleccionarPredioDetalle(predioId, predioTId, numero);
      }
    });

    // Map variables and logic for detailing assignments
    const ASSIGN_WMS_URL_DETAIL = `${rp}/geoserver/B_ASIGNACIONES_ARB/wms`;
    const ASSIGN_WFS_URL_DETAIL = `${rp}/geoserver/B_ASIGNACIONES_ARB/wfs`;
    const USE_GEOSERVER_STYLES_DETAIL = false;
    const SHOULD_USE_WMS_DETAIL = USE_GEOSERVER_STYLES_DETAIL && Boolean(ASSIGN_WMS_LAYER_DETAIL);
    const DEFAULT_PROJECT_EXTENT_DETAIL = [4508003.5, 1760960.25, 4532217.0, 1793534.0];
    let projectExtentDetail = [...DEFAULT_PROJECT_EXTENT_DETAIL];
    let assignmentExtentDetail = null;
    let mapInstanceDetail = null;
    let assignmentWmsLayerDetail = null;
    let assignmentPrediosLayerDetail = null;
    let assignmentTerrenosLayerDetail = null;
    let assignmentUcLayerDetail = null;
    let assignedScopeLayerDetail = null;
    let highlightLayerDetail = null;
    let currentPredioFeatureDetail = null;
    let wmsScopedAppliedDetail = false;
    let pendingWmsFiltersDetail = [];
    let activeWmsFilterIdxDetail = -1;
    let wmsFieldNamesDetail = null;
    let detallePredioCacheDetail = new Map();
    let detallePredioRequestSeqDetail = 0;

    function setVectorScopeModeDetail() {
      assignmentWmsLayerDetail?.setVisible(false);
      assignmentTerrenosLayerDetail?.setVisible(false);
      assignmentPrediosLayerDetail?.setVisible(false);
      assignmentUcLayerDetail?.setVisible(true);
      assignedScopeLayerDetail?.setVisible(true);
    }

    function setWmsScopeModeDetail() {
      assignmentWmsLayerDetail?.setVisible(true);
      assignmentTerrenosLayerDetail?.setVisible(false);
      assignmentPrediosLayerDetail?.setVisible(false);
      assignmentUcLayerDetail?.setVisible(false);
      assignedScopeLayerDetail?.setVisible(false);
    }

    if (window.proj4 && window.ol) {
      proj4.defs(
        "EPSG:9377",
        "+proj=tmerc +lat_0=4 +lon_0=-73 +k=0.9992 +x_0=5000000 +y_0=2000000 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs +type=crs"
      );
      ol.proj.proj4.register(proj4);
    }

    function isValidExtentDetail(extent) {
      if (!Array.isArray(extent) || extent.length !== 4) return false;
      const values = extent.map((v) => Number(v));
      return (
        values.every((v) => Number.isFinite(v)) &&
        values[0] < values[2] &&
        values[1] < values[3]
      );
    }

    async function loadProjectExtentDetail() {
      try {
        const r = await fetch(`${rp}/visor/project-extent`, { credentials: "same-origin" });
        if (!r.ok) return;
        const data = await r.json().catch(() => ({}));
        if (!isValidExtentDetail(data?.extent)) return;
        projectExtentDetail = data.extent.map((v) => Number(v));
        if (mapInstanceDetail) {
          mapInstanceDetail.getView().fit(projectExtentDetail, {
            padding: [40, 40, 40, 40],
            duration: 300
          });
        }
      } catch (_err) { }
    }

    function initMapDetail() {
      if (!window.ol) return;
      if (mapInstanceDetail) return;
      const mapTarget = document.getElementById("map");
      if (!mapTarget) return;

      const projection = ol.proj.get("EPSG:9377");
      assignmentTerrenosLayerDetail = new ol.layer.Vector({
        source: new ol.source.Vector(),
        style: new ol.style.Style({
          stroke: new ol.style.Stroke({ color: "#f59e0b", width: 1.8 }),
          fill: new ol.style.Fill({ color: "rgba(245, 158, 11, 0.12)" }),
        }),
        visible: !SHOULD_USE_WMS_DETAIL,
      });

      assignedScopeLayerDetail = new ol.layer.Vector({
        source: new ol.source.Vector(),
        style: new ol.style.Style({
          stroke: new ol.style.Stroke({ color: "#16a34a", width: 2 }),
          fill: new ol.style.Fill({ color: "rgba(34, 197, 94, 0.14)" }),
        }),
        visible: true,
        zIndex: 24,
      });

      assignmentPrediosLayerDetail = new ol.layer.Vector({
        source: new ol.source.Vector(),
        style: new ol.style.Style({
          stroke: new ol.style.Stroke({ color: "#0ea5e9", width: 2.2 }),
          fill: new ol.style.Fill({ color: "rgba(14, 165, 233, 0.10)" }),
        }),
        visible: !SHOULD_USE_WMS_DETAIL,
      });

      assignmentUcLayerDetail = new ol.layer.Vector({
        source: new ol.source.Vector(),
        style: new ol.style.Style({
          stroke: new ol.style.Stroke({ color: "#ef4444", width: 1.8 }),
          fill: new ol.style.Fill({ color: "rgba(0, 0, 0, 0)" }),
        }),
        visible: !SHOULD_USE_WMS_DETAIL,
      });

      highlightLayerDetail = new ol.layer.Vector({
        source: new ol.source.Vector(),
        style: new ol.style.Style({
          stroke: new ol.style.Stroke({ color: "#2563eb", width: 3.5 }),
          fill: new ol.style.Fill({ color: "rgba(37, 99, 235, 0.24)" }),
        }),
      });

      const osmLayer = new ol.layer.Tile({
        source: new ol.source.OSM(),
        visible: true,
      });

      assignmentWmsLayerDetail = new ol.layer.Tile({
        source: new ol.source.TileWMS({
          url: ASSIGN_WMS_URL_DETAIL,
          params: {
            "LAYERS": ASSIGN_WMS_LAYER_DETAIL,
            "TILED": true,
            "VERSION": "1.1.0",
            "FORMAT": "image/png",
            "TRANSPARENT": true,
            "SRS": "EPSG:9377",
          },
          serverType: "geoserver",
          crossOrigin: "anonymous",
          transition: 0,
        }),
        visible: false,
        opacity: 0.85,
        zIndex: 20,
      });

      const enableVectorFallbackDetail = () => {
        setVectorScopeModeDetail();
        wmsScopedAppliedDetail = false;
        pendingWmsFiltersDetail = [];
        activeWmsFilterIdxDetail = -1;
      };

      const applyWmsFilterByIndexDetail = (idx) => {
        if (!assignmentWmsLayerDetail?.getSource) return false;
        if (!Array.isArray(pendingWmsFiltersDetail) || idx < 0 || idx >= pendingWmsFiltersDetail.length) return false;
        const cql = pendingWmsFiltersDetail[idx];
        activeWmsFilterIdxDetail = idx;
        console.info("[asignaciones_detalle] Aplicando CQL_FILTER:", cql);
        assignmentWmsLayerDetail.getSource().updateParams({
          "CQL_FILTER": cql,
          "STYLES": "",
        });
        setWmsScopeModeDetail();
        return true;
      };

      if (SHOULD_USE_WMS_DETAIL) {
        const wmsSource = assignmentWmsLayerDetail.getSource();
        wmsSource?.on?.("tileloaderror", () => {
          const nextIdx = activeWmsFilterIdxDetail + 1;
          if (Array.isArray(pendingWmsFiltersDetail) && nextIdx < pendingWmsFiltersDetail.length) {
            console.warn("[asignaciones_detalle] CQL_FILTER no válido, probando siguiente candidato.");
            if (applyWmsFilterByIndexDetail(nextIdx)) return;
          }
          console.warn("[asignaciones_detalle] WMS no disponible o filtro inválido; activando fallback.");
          enableVectorFallbackDetail();
        });
      } else {
        enableVectorFallbackDetail();
      }

      highlightLayerDetail.setZIndex(30);

      mapInstanceDetail = new ol.Map({
        target: "map",
        layers: [
          osmLayer,
          assignmentWmsLayerDetail,
          assignmentTerrenosLayerDetail,
          assignmentPrediosLayerDetail,
          assignmentUcLayerDetail,
          assignedScopeLayerDetail,
          highlightLayerDetail,
        ],
        view: new ol.View({
          projection: projection,
          center: ol.extent.getCenter(projectExtentDetail),
          zoom: 2,
        }),
      });
    }

    function clearAssignmentScopeGeometryDetail() {
      assignmentExtentDetail = null;
      assignmentPrediosLayerDetail?.getSource?.().clear();
      assignmentTerrenosLayerDetail?.getSource?.().clear();
      assignmentUcLayerDetail?.getSource?.().clear();
      assignedScopeLayerDetail?.getSource?.().clear();
      if (assignmentWmsLayerDetail?.getSource) {
        assignmentWmsLayerDetail.getSource().updateParams({
          "CQL_FILTER": null,
          "STYLES": "",
        });
        setVectorScopeModeDetail();
      }
      wmsScopedAppliedDetail = false;
      pendingWmsFiltersDetail = [];
      activeWmsFilterIdxDetail = -1;
    }

    function _applyScopedWmsFilterDetail(scopePayload = {}) {
      if (!SHOULD_USE_WMS_DETAIL || !assignmentWmsLayerDetail?.getSource) return false;
      const asigId = Number(scopePayload?.asignacion_id);
      const workDataset = String(scopePayload?.work_datasetname ?? "").trim();
      if (!workDataset) return false;
      const basketIdsSet = new Set();
      const predialSet = new Set();
      const pushBasket = (v) => {
        const n = Number(v);
        if (Number.isInteger(n) && n > 0) basketIdsSet.add(n);
      };
      const pushPredial = (v) => {
        const s = String(v ?? "").trim();
        if (s) predialSet.add(s);
      };

      if (Array.isArray(scopePayload?.basket_ids)) {
        scopePayload.basket_ids.forEach(pushBasket);
      }

      const predioFeatures = Array.isArray(scopePayload?.predios?.features) ? scopePayload.predios.features : [];
      const terrenoFeatures = Array.isArray(scopePayload?.terrenos?.features) ? scopePayload.terrenos.features : [];
      const ucFeatures = Array.isArray(scopePayload?.unidades_construccion?.features) ? scopePayload.unidades_construccion.features : [];
      predioFeatures.forEach((f) => {
        pushBasket(f?.properties?.basket_id);
        pushPredial(f?.properties?.numero_predial_nacional);
      });
      terrenoFeatures.forEach((f) => {
        pushBasket(f?.properties?.basket_id);
        pushPredial(f?.properties?.numero_predial_nacional);
      });
      ucFeatures.forEach((f) => {
        pushBasket(f?.properties?.basket_id);
        pushPredial(f?.properties?.numero_predial_nacional);
      });

      const basketIds = Array.from(basketIdsSet.values()).sort((a, b) => a - b);
      const prediales = Array.from(predialSet.values());

      const filters = [];
      const fields = Array.isArray(wmsFieldNamesDetail) ? wmsFieldNamesDetail : [];
      const fieldByLower = new Map(fields.map((f) => [String(f).toLowerCase(), f]));
      const pickField = (...names) => {
        for (const name of names) {
          const found = fieldByLower.get(String(name).toLowerCase());
          if (found) return found;
        }
        return null;
      };
      const fNumPredial = pickField("numero_predial", "numero_predial_nacional", "predio_numero_predial")
        || "numero_predial";
      const fBasket = pickField("t_basket", "basket", "t_basket_id")
        || "t_basket";
      const fAsigId = pickField("asignacion_id", "id_asignacion", "asignacion");
      const fDataset = pickField("work_datasetname", "datasetname", "dataset_name");

      if (Number.isInteger(asigId) && asigId > 0 && fAsigId) {
        filters.push(`${fAsigId} = ${asigId}`);
      }
      if (workDataset && fDataset) {
        const dsQuoted = workDataset.replace(/'/g, "''");
        filters.push(`${fDataset} = '${dsQuoted}'`);
      }
      if (Number.isInteger(asigId) && asigId > 0 && fAsigId && workDataset && fDataset) {
        const dsQuoted = workDataset.replace(/'/g, "''");
        filters.push(`${fAsigId} = ${asigId} AND ${fDataset} = '${dsQuoted}'`);
      }

      if (prediales.length) {
        const quotedVals = prediales.map((v) => `'${v.replace(/'/g, "''")}'`).join(",");
        filters.push(`${fNumPredial} IN (${quotedVals})`);
        if (fNumPredial !== "numero_predial_nacional") {
          filters.push(`numero_predial_nacional IN (${quotedVals})`);
        }
        if (fNumPredial !== "predio_numero_predial") {
          filters.push(`predio_numero_predial IN (${quotedVals})`);
        }
      }
      if (basketIds.length) {
        filters.push(`${fBasket} IN (${basketIds.join(",")})`);
        if (fBasket !== "t_basket") {
          filters.push(`t_basket IN (${basketIds.join(",")})`);
        }
      }
      if (!filters.length) return false;

      pendingWmsFiltersDetail = filters;
      activeWmsFilterIdxDetail = -1;
      const cql = pendingWmsFiltersDetail[0];
      assignmentWmsLayerDetail.getSource().updateParams({
        "CQL_FILTER": cql,
        "STYLES": "",
      });
      console.info("[asignaciones_detalle] Aplicando CQL_FILTER:", cql);
      setWmsScopeModeDetail();
      activeWmsFilterIdxDetail = 0;
      wmsScopedAppliedDetail = true;
      return true;
    }

    async function _loadWmsFieldNamesDetail() {
      if (!SHOULD_USE_WMS_DETAIL) return [];
      if (Array.isArray(wmsFieldNamesDetail) && wmsFieldNamesDetail.length) return wmsFieldNamesDetail;
      try {
        const u = new URL(ASSIGN_WFS_URL_DETAIL, window.location.origin);
        u.searchParams.set("service", "WFS");
        u.searchParams.set("version", "1.1.0");
        u.searchParams.set("request", "DescribeFeatureType");
        u.searchParams.set("typeName", ASSIGN_WMS_LAYER_DETAIL);
        u.searchParams.set("typename", ASSIGN_WMS_LAYER_DETAIL);
        const r = await fetch(u.toString(), { credentials: "same-origin" });
        if (!r.ok) return [];
        const xml = await r.text();
        const doc = new DOMParser().parseFromString(xml, "text/xml");
        const els = Array.from(doc.getElementsByTagNameNS("*", "element"));
        const names = els
          .map((el) => String(el.getAttribute("name") || "").trim())
          .filter(Boolean);
        wmsFieldNamesDetail = names;
        console.info("[asignaciones_detalle] Campos WMS detectados:", names);
        return names;
      } catch (_err) {
        return [];
      }
    }

    function _readFeaturesSmartDetail(collection) {
      const fc = collection && collection.type === "FeatureCollection"
        ? collection
        : { type: "FeatureCollection", features: [] };
      const format = new ol.format.GeoJSON();
      try {
        return format.readFeatures(fc, {
          dataProjection: "EPSG:9377",
          featureProjection: "EPSG:9377",
        });
      } catch (_e) {
        try {
          return format.readFeatures(fc, {
            dataProjection: "EPSG:4326",
            featureProjection: "EPSG:9377",
          });
        } catch (_e2) {
          return [];
        }
      }
    }

    async function loadAssignmentScopeDetalle(asignacionId) {
      initMapDetail();
      if (!mapInstanceDetail) return;
      clearAssignmentScopeGeometryDetail();
      await _loadWmsFieldNamesDetail();

      const idNum = Number(asignacionId);
      if (!idNum || idNum < 1) return;

      try {
        const resp = await fetch(`${rp}/asignaciones/${encodeURIComponent(idNum)}/scope-geojson`, {
          credentials: "same-origin",
          headers: { "Accept": "application/json" }
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) return;

        const predioFeatures = _readFeaturesSmartDetail(data?.predios);
        const terrenoFeatures = _readFeaturesSmartDetail(data?.terrenos);
        const ucFeatures = _readFeaturesSmartDetail(data?.unidades_construccion);

        assignmentPrediosLayerDetail?.getSource?.().addFeatures(predioFeatures);
        assignmentTerrenosLayerDetail?.getSource?.().addFeatures(terrenoFeatures);
        assignmentUcLayerDetail?.getSource?.().addFeatures(ucFeatures);
        const assignedFeatures = terrenoFeatures.length
          ? terrenoFeatures
          : (ucFeatures.length ? ucFeatures : predioFeatures);
        assignedScopeLayerDetail?.getSource?.().addFeatures(assignedFeatures);

        if (!_applyScopedWmsFilterDetail(data)) {
          setVectorScopeModeDetail();
        }

        let combinedExtent = null;
        const appendExtent = (extent) => {
          if (!extent || !isValidExtentDetail(extent)) return;
          if (!combinedExtent) {
            combinedExtent = extent.slice();
            return;
          }
          ol.extent.extend(combinedExtent, extent);
        };
        if (predioFeatures.length) {
          appendExtent(assignmentPrediosLayerDetail.getSource().getExtent());
        }
        if (terrenoFeatures.length) {
          appendExtent(assignmentTerrenosLayerDetail.getSource().getExtent());
        }
        if (ucFeatures.length) {
          appendExtent(assignmentUcLayerDetail.getSource().getExtent());
        }

        if (combinedExtent && isValidExtentDetail(combinedExtent)) {
          assignmentExtentDetail = combinedExtent;
          mapInstanceDetail.getView().fit(assignmentExtentDetail, {
            padding: [40, 40, 40, 40],
            duration: 500,
            maxZoom: 19,
          });
        }
      } catch (_err) { }
    }

    function zoomToProjectDetalle() {
      if (!mapInstanceDetail) return;
      const targetExtent = isValidExtentDetail(assignmentExtentDetail) ? assignmentExtentDetail : projectExtentDetail;
      mapInstanceDetail.getView().fit(targetExtent, {
        padding: [40, 40, 40, 40],
        duration: 450,
      });
    }

    function zoomToPredioDetalle() {
      if (!mapInstanceDetail || !currentPredioFeatureDetail) return;
      mapInstanceDetail.getView().fit(currentPredioFeatureDetail.getGeometry().getExtent(), {
        padding: [40, 40, 40, 40],
        duration: 450,
        maxZoom: 20,
      });
    }

    function clearPredioGeometryDetalle() {
      currentPredioFeatureDetail = null;
      if (highlightLayerDetail?.getSource) {
        highlightLayerDetail.getSource().clear();
      }
    }

    function _parseGeometryCandidateDetalle(value) {
      if (!value) return null;
      if (typeof value === "string") {
        const text = value.trim();
        if (!text) return null;
        try {
          const parsed = JSON.parse(text);
          return _parseGeometryCandidateDetalle(parsed);
        } catch (_e) {
          return null;
        }
      }
      if (typeof value !== "object") return null;
      if (!value.type) return null;
      if (value.type === "Feature" && value.geometry) return value.geometry;
      if (Array.isArray(value.coordinates)) return value;
      return null;
    }

    function extractPredioGeometryDetalle(predioRecord = {}) {
      const candidates = Object.values(predioRecord || {});
      for (const candidate of candidates) {
        const parsed = _parseGeometryCandidateDetalle(candidate);
        if (parsed) return parsed;
      }
      return null;
    }

    function findAssignedGeometryByNumeroPredialDetalle(numeroPredial) {
      const npn = String(numeroPredial ?? "").trim();
      if (!npn || !assignedScopeLayerDetail?.getSource) return null;
      const features = assignedScopeLayerDetail.getSource().getFeatures() || [];
      for (const feature of features) {
        const val = String(feature?.get?.("numero_predial_nacional") ?? "").trim();
        if (val && val === npn) {
          const g = feature.getGeometry?.();
          if (g) return g.clone();
        }
      }
      return null;
    }

    function updateMapWithPredioDetalle(detalle = {}, numeroPredial = "") {
      initMapDetail();
      if (!mapInstanceDetail || !highlightLayerDetail) return;
      clearPredioGeometryDetalle();

      const geometryObj = extractPredioGeometryDetalle(detalle?.predio || {});
      const format = new ol.format.GeoJSON();
      let geometry = null;
      if (geometryObj) {
        try {
          geometry = format.readGeometry(geometryObj, {
            dataProjection: "EPSG:9377",
            featureProjection: "EPSG:9377",
          });
        } catch (_e) { }
        if (!geometry) {
          try {
            geometry = format.readGeometry(geometryObj, {
              dataProjection: "EPSG:4326",
              featureProjection: "EPSG:9377",
            });
          } catch (_e) { }
        }
      }
      if (!geometry) {
        geometry = findAssignedGeometryByNumeroPredialDetalle(numeroPredial);
      }
      if (!geometry) return;

      currentPredioFeatureDetail = new ol.Feature({ geometry });
      highlightLayerDetail.getSource().addFeature(currentPredioFeatureDetail);
      zoomToPredioDetalle();
    }

    async function fetchDetallePredioDetalle(asignacionId, predioTId) {
      const asigKey = String(asignacionId ?? "").trim();
      const predioKey = String(predioTId ?? "").trim();
      if (!asigKey || !predioKey) return null;

      const key = `${asigKey}:${predioKey}`;

      if (detallePredioCacheDetail.has(key)) {
        return detallePredioCacheDetail.get(key);
      }

      const resp = await fetch(
        `${rp}/asignaciones/${encodeURIComponent(asigKey)}/predios/${encodeURIComponent(predioKey)}/detalle-completo`,
        {
          credentials: "same-origin"
        }
      );
      const data = await resp.json().catch(() => ({}));

      if (!resp.ok) {
        throw new Error(data?.detail || data?.error || "No se pudo cargar el detalle del predio.");
      }

      detallePredioCacheDetail.set(key, data);
      return data;
    }

    async function seleccionarPredioDetalle(predioId, predioTId, numeroPredial) {
      const asignacionId = Number(elId?.value || idFromUrl);
      if (!asignacionId || asignacionId < 1) {
        console.error("No se pudo seleccionar predio: ID de asignación inválido.");
        return;
      }

      predioSeleccionadoDetalleId = predioId;
      predioSeleccionadoTId = predioTId;
      predioSeleccionadoNumero = numeroPredial;

      syncPredioSelectionUI();

      if (!predioTId) {
        clearPredioGeometryDetalle();
        return;
      }

      const requestSeq = ++detallePredioRequestSeqDetail;

      try {
        const detalle = await fetchDetallePredioDetalle(asignacionId, predioTId);
        if (requestSeq !== detallePredioRequestSeqDetail) return;
        if (String(predioSeleccionadoTId) !== String(predioTId)) return;

        updateMapWithPredioDetalle(detalle, numeroPredial);
        const predioObj = { id: predioId, predio_t_id: predioTId, numero_predial_nacional: numeroPredial };
        aplicarDetallePredioSeleccionadoEdit(predioObj, detalle);
      } catch (err) {
        if (requestSeq !== detallePredioRequestSeqDetail) return;
        clearPredioGeometryDetalle();
        resetDetallePredioEdit();
        console.error("Error cargando detalle del predio para el mapa:", err);
      }
    }

    document.addEventListener("DOMContentLoaded", () => {
      initMapDetail();
      loadProjectExtentDetail();
      document.getElementById("btnZoomPredio")?.addEventListener("click", zoomToPredioDetalle);
      document.getElementById("btnZoomProyecto")?.addEventListener("click", zoomToProjectDetalle);
    });

    // =========================================================================
    // INTEGRACIÓN DETALLE DEL PREDIO (LÓGICA COPIADA DE EDICION_ASIGNACIONES.HTML)
    // =========================================================================
    let prediosAsignacionDataEdit = [];
    let predioSeleccionadoEditId = null;
    let detallePredioCacheEdit = new Map();
    let detallePredioRequestSeqEdit = 0;
    let detallePredioActualEdit = null;
    let interesadosModalEditData = [];
    let construccionesDataEdit = [];
    let unidadesDataEdit = [];
    let construccionActivaEdit = null;
    let unidadActivaEdit = null;

    function normalizarTextoEdit(valor) {
      if (valor === null || valor === undefined || valor === "") return "---";
      return String(valor);
    }

    function contarUcAsociadasEdit(item) {
      if (Array.isArray(item.unidades_construccion)) return item.unidades_construccion.length;
      if (Array.isArray(item.unidades)) return item.unidades.length;
      if (item.total_unidades !== undefined && item.total_unidades !== null) return Number(item.total_unidades) || 0;
      if (item.uc_asociadas !== undefined && item.uc_asociadas !== null) return Number(item.uc_asociadas) || 0;
      return 0;
    }

    function obtenerTipoConstruccionEdit(item) {
      return (
        item.tipo_construccion_nombre ||
        item.tipo_construccion ||
        item.nombre_tipo_construccion ||
        "---"
      );
    }

    function obtenerIdentificadorConstruccionEdit(item, index = 0) {
      return (
        item.identificador ||
        item.codigo ||
        item.construccion_id ||
        item.t_id ||
        `CONS-${index + 1}`
      );
    }

    function obtenerPredioConstruccionEdit(item) {
      return (
        item.predio_numero_predial ||
        item.numero_predial ||
        item.predio ||
        "---"
      );
    }

    function obtenerListaUnidadesConstruccionEdit(item) {
      if (Array.isArray(item.unidades_construccion)) return item.unidades_construccion;
      if (Array.isArray(item.unidades)) return item.unidades;
      return [];
    }

    function actualizarBadgeUcDesdeTablaEdit() {
      const tbody = document.getElementById("tbodyUnidadConstruccionCard");
      const badgeUcActiva = document.getElementById("badgeUcActiva");
      const badgeUcValor = document.getElementById("badgeUcValor");

      if (!tbody || !badgeUcActiva || !badgeUcValor) return;

      const filas = tbody.querySelectorAll(".fila-unidad-card-principal");
      const cantidad = filas.length;

      if (!cantidad || (cantidad === 1 && tbody.querySelector(".fila-vacia-unidad"))) {
        badgeUcActiva.classList.add("d-none");
        badgeUcValor.textContent = "";
        return;
      }

      badgeUcActiva.classList.remove("d-none");
      badgeUcValor.textContent = cantidad;
    }

    function animarActualizacionUnidadEdit() {
      const card = document.getElementById("cardUnidadConstruccion");
      if (!card) return;

      card.classList.remove("animar-actualizacion-unidad");
      void card.offsetWidth;
      card.classList.add("animar-actualizacion-unidad");
    }

    function actualizarResumenConstruccionesEdit(construcciones = []) {
      setText("resumenPredioConstrucciones", construcciones.length);

      const totalUc = construcciones.reduce((acc, item) => {
        return acc + contarUcAsociadasEdit(item);
      }, 0);

      setText("resumenPredioUnidadConstruccion", totalUc);
    }

    function mostrarMensajeSinSeleccionUcEdit() {
      const card = document.getElementById("cardUnidadConstruccion");
      const detalleUnidadConstruccionCard = document.getElementById("detalleUnidadConstruccionCard");
      const tbody = document.getElementById("tbodyUnidadConstruccionCard");
      const badgeConstruccionActiva = document.getElementById("badgeConstruccionActiva");
      const badgeConstruccionValor = document.getElementById("badgeConstruccionValor");
      const badgeUcActiva = document.getElementById("badgeUcActiva");
      const badgeUcValor = document.getElementById("badgeUcValor");

      construccionActivaEdit = null;
      unidadActivaEdit = null;
      unidadesDataEdit = [];

      if (card) card.classList.remove("has-selection");

      if (badgeConstruccionActiva) badgeConstruccionActiva.classList.add("d-none");
      if (badgeConstruccionValor) badgeConstruccionValor.textContent = "";
      if (badgeUcActiva) badgeUcActiva.classList.add("d-none");
      if (badgeUcValor) badgeUcValor.textContent = "";

      if (tbody) {
        tbody.innerHTML = `
              <tr class="fila-vacia-unidad">
                  <td colspan="5" class="text-center text-muted py-3">
                      Sin información de unidad de construcción
                  </td>
              </tr>
          `;
      }

      if (detalleUnidadConstruccionCard) {
        const instance = bootstrap.Collapse.getOrCreateInstance(detalleUnidadConstruccionCard, { toggle: false });
        instance.hide();
      }
    }

    function actualizarBadgeConstruccionActivaEdit(construccion) {
      const card = document.getElementById("cardUnidadConstruccion");
      const badgeConstruccionActiva = document.getElementById("badgeConstruccionActiva");
      const badgeConstruccionValor = document.getElementById("badgeConstruccionValor");

      if (!card || !badgeConstruccionActiva || !badgeConstruccionValor) return;

      card.classList.add("has-selection");
      badgeConstruccionActiva.classList.remove("d-none");
      badgeConstruccionValor.textContent = obtenerIdentificadorConstruccionEdit(construccion);
    }

    function renderTablaConstruccionesEdit(construcciones = []) {
      const tabla = document.getElementById("tblConsCollapse");
      const tbody = document.getElementById("tbodyConsCollapse");
      const empty = document.getElementById("emptyConsCollapse");

      if (!tabla || !tbody || !empty) return;

      construccionesDataEdit = Array.isArray(construcciones) ? construcciones : [];

      if (!construccionesDataEdit.length) {
        tabla.style.display = "none";
        empty.style.display = "block";
        tbody.innerHTML = "";
        mostrarMensajeSinSeleccionUcEdit();
        actualizarResumenConstruccionesEdit([]);
        return;
      }

      tabla.style.display = "";
      empty.style.display = "none";

      tbody.innerHTML = construccionesDataEdit.map((item, index) => {
        const rowId = `detalleConstruccionEdit_${index}`;
        const identificador = normalizarTextoEdit(obtenerIdentificadorConstruccionEdit(item, index));
        const tipo = normalizarTextoEdit(obtenerTipoConstruccionEdit(item));
        const predio = normalizarTextoEdit(obtenerPredioConstruccionEdit(item));
        const totalUc = contarUcAsociadasEdit(item);

        const tipoDominio = normalizarTextoEdit(item?.tipo_dominio_nombre);
        const totalMezaninis = normalizarTextoEdit(item?.total_mezaninis);
        const etiqueta = normalizarTextoEdit(item?.etiqueta);
        const totalPisos = normalizarTextoEdit(item?.total_pisos);
        const totalSemisotanos = normalizarTextoEdit(item?.total_semisotanos);
        const estadoConstruccion = normalizarTextoEdit(item?.estado_construccion_nombre);
        const totalSotanos = normalizarTextoEdit(item?.total_sotanos);
        const areaTotalConstruccion = normalizarTextoEdit(item?.area_total_construccion);
        const observacion = normalizarTextoEdit(item?.observacion);

        return `
              <tr class="fila-unidad-collapse" data-index="${index}">
                  <td class="text-center">
                      <button
                          class="btn btn-toggle-detalle-uc p-0 border-0 bg-transparent shadow-none"
                          type="button"
                          data-bs-toggle="collapse"
                          data-bs-target="#${rowId}"
                          aria-expanded="false"
                          aria-controls="${rowId}">
                          <i class="fa-solid fa-chevron-down icon-toggle-uc"></i>
                      </button>
                  </td>
                  <td class="text-center text-detalle-unidad">${identificador}</td>
                  <td class="text-center text-detalle-unidad">${tipo}</td>
                  <td class="text-center text-detalle-unidad">${predio}</td>
                  <td class="text-center text-detalle-unidad">${totalUc}</td>
              </tr>

              <tr class="fila-detalle-unidad">
                  <td colspan="5" class="p-0 border-0">
                      <div class="collapse collapse-detalle-cons-edit" id="${rowId}">
                          <div class="detalle-unidad-contenido px-5 pt-2 pb-4 ms-5">
                              <div class="row gx-5 gy-4 mb-4">
                                  <div class="col-12 col-md-4">
                                      <div class="fw-bold mb-1 text-detalle-unidad">Tipo dominio</div>
                                      <div class="detalle-uc-value">${tipoDominio}</div>
                                  </div>
                                  <div class="col-12 col-md-4">
                                      <div class="fw-bold mb-1 text-detalle-unidad">Total mezaninis</div>
                                      <div class="detalle-uc-value">${totalMezaninis}</div>
                                  </div>
                                  <div class="col-12 col-md-4">
                                      <div class="fw-bold mb-1 text-detalle-unidad">Etiqueta</div>
                                      <div class="detalle-uc-value">${etiqueta}</div>
                                  </div>
                              </div>
                              <div class="row gx-5 gy-4 mb-4">
                                  <div class="col-12 col-md-4">
                                      <div class="fw-bold mb-1 text-detalle-unidad">Total pisos</div>
                                      <div class="detalle-uc-value">${totalPisos}</div>
                                  </div>
                                  <div class="col-12 col-md-4">
                                      <div class="fw-bold mb-1 text-detalle-unidad">Total semisotanos</div>
                                      <div class="detalle-uc-value">${totalSemisotanos}</div>
                                  </div>
                                  <div class="col-12 col-md-4">
                                      <div class="fw-bold mb-1 text-detalle-unidad">Estado construccion</div>
                                      <div class="detalle-uc-value">${estadoConstruccion}</div>
                                  </div>
                              </div>
                              <div class="row gx-5 gy-4 mb-4">
                                  <div class="col-12 col-md-4">
                                      <div class="fw-bold mb-1 text-detalle-unidad">Total Sotanos</div>
                                      <div class="detalle-uc-value">${totalSotanos}</div>
                                  </div>
                                  <div class="col-12 col-md-4">
                                      <div class="fw-bold mb-1 text-detalle-unidad">Total construccion</div>
                                      <div class="detalle-uc-value">${areaTotalConstruccion}</div>
                                  </div>
                                  <div class="col-12 col-md-4">
                                      <div class="fw-bold mb-1 text-detalle-unidad">Observación</div>
                                      <div class="detalle-uc-value">${observacion}</div>
                                  </div>
                              </div>
                          </div>
                      </div>
                  </td>
              </tr>
          `;
      }).join("");

      tbody.querySelectorAll(".fila-unidad-collapse").forEach((row) => {
        row.addEventListener("click", (event) => {
          if (event.target.closest("button")) return;

          const index = Number(row.dataset.index);
          seleccionarConstruccionEdit(index);

          const collapseEl = document.getElementById(`detalleConstruccionEdit_${index}`);
          if (!collapseEl) return;

          const instance = bootstrap.Collapse.getOrCreateInstance(collapseEl, { toggle: false });
          if (collapseEl.classList.contains("show")) {
            instance.hide();
          } else {
            instance.show();
          }
        });
      });

      tbody.querySelectorAll(".collapse-detalle-cons-edit").forEach((collapseEl) => {
        collapseEl.addEventListener("show.bs.collapse", () => {
          tbody.querySelectorAll(".collapse-detalle-cons-edit.show").forEach((openEl) => {
            if (openEl.id !== collapseEl.id) {
              bootstrap.Collapse.getOrCreateInstance(openEl, { toggle: false }).hide();
            }
          });

          tbody.querySelectorAll(".fila-unidad-collapse").forEach((row) => {
            row.classList.remove("detalle-activo");
            const icon = row.querySelector(".icon-toggle-uc");
            if (icon) {
              icon.classList.remove("fa-chevron-up");
              icon.classList.add("fa-chevron-down");
            }
          });

          tbody.querySelectorAll(".fila-detalle-unidad").forEach((row) => {
            row.classList.remove("detalle-activo");
          });

          const detailRow = collapseEl.closest(".fila-detalle-unidad");
          const principalRow = detailRow?.previousElementSibling;

          if (principalRow) {
            principalRow.classList.add("detalle-activo");
            const icon = principalRow.querySelector(".icon-toggle-uc");
            if (icon) {
              icon.classList.remove("fa-chevron-down");
              icon.classList.add("fa-chevron-up");
            }
          }

          if (detailRow) {
            detailRow.classList.add("detalle-activo");
          }
        });

        collapseEl.addEventListener("hide.bs.collapse", () => {
          const detailRow = collapseEl.closest(".fila-detalle-unidad");
          const principalRow = detailRow?.previousElementSibling;

          if (principalRow) {
            principalRow.classList.remove("detalle-activo");
            const icon = principalRow.querySelector(".icon-toggle-uc");
            if (icon) {
              icon.classList.remove("fa-chevron-up");
              icon.classList.add("fa-chevron-down");
            }
          }

          if (detailRow) {
            detailRow.classList.remove("detalle-activo");
          }
        });
      });

      actualizarResumenConstruccionesEdit(construccionesDataEdit);
    }

    function resolverEtiquetaUnidadEdit(item = {}) {
      const etiquetaDirecta =
        item.etiqueta ??
        item.etiqueta_uc ??
        item.nombre ??
        item.nombre_uc;

      if (etiquetaDirecta && String(etiquetaDirecta).trim() !== "") {
        return etiquetaDirecta;
      }

      const identificador =
        item.identificador ??
        item.codigo ??
        item.t_id ??
        "";

      const tipoUc =
        item.tipo_unidad_construccion_nombre ||
        item.tipo_uc_nombre ||
        item.tipo_uc ||
        "";

      if (tipoUc && identificador) return `${tipoUc} ${identificador}`;
      if (tipoUc) return tipoUc;
      if (identificador) return identificador;

      return "---";
    }

    function renderUnidadConstruccionCardEdit(unidades = []) {
      const tbody = document.getElementById("tbodyUnidadConstruccionCard");
      const detalleUnidadConstruccionCard = document.getElementById("detalleUnidadConstruccionCard");

      if (!tbody || !detalleUnidadConstruccionCard) return;

      unidadesDataEdit = Array.isArray(unidades) ? unidades : [];

      if (!unidadesDataEdit.length) {
        tbody.innerHTML = `
              <tr class="fila-vacia-unidad">
                  <td colspan="5" class="text-center text-muted py-3">
                      Sin información de unidad de construcción
                  </td>
              </tr>
          `;
        actualizarBadgeUcDesdeTablaEdit();
        return;
      }

      tbody.innerHTML = unidadesDataEdit.map((item, index) => {
        const rowId = `detalleFilaUnidadCardEdit_${item?.t_id ?? item?.unidad_id ?? index}`;
        const unitId = item?.t_id ?? item?.unidad_id ?? index;
        const plantaUbicacion = normalizarTextoEdit(item?.planta_ubicacion);
        const altura = normalizarTextoEdit(item?.altura);
        const etiqueta = normalizarTextoEdit(resolverEtiquetaUnidadEdit(item));
        const identificador = normalizarTextoEdit(item?.identificador ?? item?.codigo ?? item?.t_id ?? "---");
        const tipoPlanta = normalizarTextoEdit(item?.tipo_planta_nombre);
        const relacionSuperficie = normalizarTextoEdit(item?.relacion_superficie_nombre);
        const estadoUnidad = normalizarTextoEdit(item?.estado_unidad_construccion_nombre ?? item?.estado_construccion ?? "Vigente");
        const observaciones = normalizarTextoEdit(item?.observaciones);
        const tipoCalificacionModal = item?.tipo_calificacion_modal ?? null;
        const unidadId = item?.t_id ?? item?.unidad_id ?? item?.id ?? null;
        const tipoUcNombre = normalizarTextoEdit(item?.tipo_unidad_construccion_nombre || item?.tipo_uc_nombre || item?.tipo_uc);

        return `
              <tr class="fila-registro-unidad fila-unidad-card-principal" data-row-id="${rowId}" data-unit-id="${unitId}">
                  <td class="text-center align-middle">
                      <button
                          class="btn btn-toggle-detalle-uc p-0 border-0 bg-transparent shadow-none"
                          type="button"
                          data-bs-toggle="collapse"
                          data-bs-target="#${rowId}"
                          aria-expanded="false"
                          aria-controls="${rowId}">
                          <i class="fa-solid fa-chevron-down icon-toggle-uc"></i>
                      </button>
                  </td>
                  <td class="text-center align-middle text-unidad-card">${plantaUbicacion}</td>
                  <td class="text-center align-middle text-unidad-card">${cutString(altura, 10)}</td>
                  <td class="text-center align-middle text-unidad-card">${cutString(tipoUcNombre, 25)}</td>
                  <td class="text-center align-middle text-unidad-card">${cutString(identificador, 25)}</td>
              </tr>

              <tr class="fila-detalle-unidad-card">
                  <td colspan="5" class="p-0 border-0">
                      <div class="collapse collapse-detalle-uc-card-edit" id="${rowId}">
                          <div class="detalle-unidad-card-contenido px-4 px-md-4 px-lg-5 pt-3 pb-3">
                              <div class="row gy-4 gx-4 gx-lg-5 align-items-start">
                                  <div class="col-12 col-md-7 col-lg-4">
                                      <div class="detalle-uc-label">Tipo de planta</div>
                                      <div class="detalle-uc-value">${tipoPlanta}</div>
                                  </div>

                                  <div class="col-12 col-md-7 col-lg-4">
                                      <div class="detalle-uc-label">Relación superficie</div>
                                      <div class="detalle-uc-value">${relacionSuperficie}</div>
                                  </div>

                                  <div class="col-12 col-md-7 col-lg-4">
                                      <div class="detalle-uc-label">Estado unidad construcción</div>
                                      <div class="detalle-uc-value">${estadoUnidad}</div>
                                  </div>
                              </div>

                              <div class="row gy-3 gx-4 gx-lg-5 mt-1 align-items-end">
                                  <div class="col-12 col-lg-4">
                                      <div class="detalle-uc-label">Etiqueta</div>
                                      <div class="detalle-uc-value">${etiqueta}</div>
                                  </div>

                                  <div class="col-12 col-lg-8">
                                      <div class="detalle-uc-label">Observaciones</div>
                                      <div class="detalle-uc-value">${observaciones}</div>
                                  </div>
                                  <div class="col-12 col-lg-4">
                                    <div class="detalle-uc-acciones d-flex justify-content-lg-end">
                                      <button
                                        type="button"
                                        class="btn btn-caracteristicas-uc"
                                        data-identificador="${identificador}"
                                        data-tipo="${tipoCalificacionModal ?? ''}"
                                        data-unidad-id="${unidadId ?? ''}"
                                      >
                                        Ver características
                                      </button>
                                    </div>
                                  </div>
                              </div>
                          </div>
                      </div>
                  </td>
              </tr>
          `;
      }).join("");

      tbody.querySelectorAll(".fila-unidad-card-principal").forEach((row) => {
        row.addEventListener("click", (event) => {
          if (event.target.closest("button")) return;

          const rowId = row.dataset.rowId;
          const unitId = row.dataset.unitId;

          seleccionarUnidadEdit(unitId);

          const collapseEl = document.getElementById(rowId);
          if (!collapseEl) return;

          const instance = bootstrap.Collapse.getOrCreateInstance(collapseEl, { toggle: false });
          if (collapseEl.classList.contains("show")) {
            instance.hide();
          } else {
            instance.show();
          }
        });
      });

      tbody.querySelectorAll(".collapse-detalle-uc-card-edit").forEach((collapseEl) => {
        collapseEl.addEventListener("show.bs.collapse", () => {
          tbody.querySelectorAll(".collapse-detalle-uc-card-edit.show").forEach((openEl) => {
            if (openEl.id !== collapseEl.id) {
              bootstrap.Collapse.getOrCreateInstance(openEl, { toggle: false }).hide();
            }
          });

          tbody.querySelectorAll(".fila-unidad-card-principal").forEach((row) => {
            row.classList.remove("fila-unidad-card-activa");
            const icon = row.querySelector(".icon-toggle-uc");
            if (icon) {
              icon.classList.remove("fa-chevron-up");
              icon.classList.add("fa-chevron-down");
            }
          });

          tbody.querySelectorAll(".fila-detalle-unidad-card").forEach((row) => {
            row.classList.remove("fila-detalle-unidad-card-activa");
          });

          const detailRow = collapseEl.closest(".fila-detalle-unidad-card");
          const principalRow = detailRow?.previousElementSibling;

          if (principalRow) {
            principalRow.classList.add("fila-unidad-card-activa");
            const icon = principalRow.querySelector(".icon-toggle-uc");
            if (icon) {
              icon.classList.remove("fa-chevron-down");
              icon.classList.add("fa-chevron-up");
            }
          }

          if (detailRow) {
            detailRow.classList.add("fila-detalle-unidad-card-activa");
          }
        });

        collapseEl.addEventListener("hide.bs.collapse", () => {
          const detailRow = collapseEl.closest(".fila-detalle-unidad-card");
          const principalRow = detailRow?.previousElementSibling;

          if (principalRow) {
            principalRow.classList.remove("fila-unidad-card-activa");
            const icon = principalRow.querySelector(".icon-toggle-uc");
            if (icon) {
              icon.classList.remove("fa-chevron-up");
              icon.classList.add("fa-chevron-down");
            }
          }

          if (detailRow) {
            detailRow.classList.remove("fila-detalle-unidad-card-activa");
          }
        });
      });

      if (!detalleUnidadConstruccionCard.classList.contains("show")) {
        bootstrap.Collapse.getOrCreateInstance(detalleUnidadConstruccionCard, { toggle: false }).show();
      }

      tbody.querySelectorAll(".btn-caracteristicas-uc").forEach((btn) => {
        btn.addEventListener("click", async (event) => {
          event.stopPropagation();
          const identificador = btn.dataset.identificador;
          const tipo = btn.dataset.tipo || null;
          const unidadId = btn.dataset.unidadId || null;

          console.log("[btn-caracteristicas-uc] Clicked button:", { identificador, tipo, unidadId });

          if (!unidadId) {
            console.warn("[btn-caracteristicas-uc] Clicked but unidadId is missing in button dataset:", btn.dataset);
            showWarning("No se pudo obtener el identificador (unidadId) de esta unidad de construcción.");
            return;
          }

          btn.style.cursor = "wait";
          btn.disabled = true;

          try {
            let detalle = unidadDetalleCacheEdit.get(String(unidadId));
            if (!detalle) {
              console.log("[btn-caracteristicas-uc] Cache miss. Fetching details for unitId:", unidadId);
              detalle = await loadUnidadExtraEdit(unidadId);
            }
            if (detalle) {
              console.log("[btn-caracteristicas-uc] Opening offcanvas for unitId:", unidadId, "with data:", detalle);
              abrirModalSegunTipoUcEdit({
                identificador,
                tipo: tipo || detalle?.unidad?.tipo_calificacion_modal || null,
                detalle
              });
            } else {
              console.error("[btn-caracteristicas-uc] Failed to load detail for unitId:", unidadId);
              showError("No se pudo cargar la información de la unidad de construcción " + identificador);
            }
          } catch (err) {
            console.error("[btn-caracteristicas-uc] Error in click handler:", err);
            showError("Ocurrió un error al intentar abrir el panel de características: " + err.message);
          } finally {
            btn.style.cursor = "";
            btn.disabled = false;
          }
        });
      });

      actualizarBadgeUcDesdeTablaEdit();
      animarActualizacionUnidadEdit();
    }

    function cutString(str, len) {
      if (!str) return "---";
      str = String(str);
      return str.length > len ? str.substring(0, len) + "..." : str;
    }

    function seleccionarUnidadEdit(unitId) {
      unidadActivaEdit = unitId;

      const tbody = document.getElementById("tbodyUnidadConstruccionCard");
      if (!tbody) return;

      tbody.querySelectorAll(".fila-unidad-card-principal").forEach((row) => {
        const isActive = String(row.dataset.unitId) === String(unitId);
        row.classList.toggle("fila-unidad-card-activa", isActive);
      });
    }

    let unidadDetalleCacheEdit = new Map();
    let unidadDetalleActualEdit = null;

    async function loadUnidadExtraEdit(unitId) {
      if (!unitId) return;
      try {
        const resp = await fetch(`${rp}/asignaciones/unidad_detalle?unidad_id=${unitId}&schema=${encodeURIComponent(asigSchemaWork || '')}`, {
          credentials: "same-origin"
        });
        if (!resp.ok) {
          console.error("Error HTTP detalle unidad:", resp.status);
          return null;
        }

        const data = await resp.json();
        unidadDetalleActualEdit = data;
        unidadDetalleCacheEdit.set(String(data?.unidad?.t_id ?? unitId), data);
        return data;
      } catch (e) {
        console.error("Error cargando detalle de unidad:", e);
        return null;
      }
    }

    function abrirModalSegunTipoUcEdit(data = {}) {
      const { identificador = "", tipo = null, detalle = {} } = data;

      poblarOffcanvasConvencionalEdit(detalle);
      poblarOffcanvasNoConvencionalEdit(detalle);
      poblarOffcanvasTipologiaEdit(detalle);

      const offcanvasConvencional = document.getElementById("offcanvasUcConvencional");
      const offcanvasNoConvencional = document.getElementById("offcanvasUcNoConvencional");
      const offcanvasTipologia = document.getElementById("offcanvasUcTipologia");
      const tipoNormalizado = String(tipo || detalle?.unidad?.tipo_calificacion_modal || "").trim().toLowerCase();

      const idMostrar = identificador || detalle?.caracteristicas?.identificador || detalle?.unidad?.identificador || "---";
      const lblConv = document.getElementById("offcanvasUcConvencionalLabel");
      const lblNoConv = document.getElementById("offcanvasUcNoConvencionalLabel");
      const lblTip = document.getElementById("offcanvasUcTipologiaLabel");
      if (lblConv) lblConv.textContent = `ID Unidad Construcción ${idMostrar}`;
      if (lblNoConv) lblNoConv.textContent = `ID Unidad Construcción ${idMostrar}`;
      if (lblTip) lblTip.textContent = `ID Unidad Construcción ${idMostrar}`;

      const subConv = document.querySelector("#offcanvasUcConvencional .subtitulo-offcanvas-uc");
      const subNoConv = document.querySelector("#offcanvasUcNoConvencional .subtitulo-offcanvas-uc");
      const subTip = document.querySelector("#offcanvasUcTipologia .subtitulo-offcanvas-uc");
      if (subConv) subConv.textContent = idMostrar;
      if (subNoConv) subNoConv.textContent = idMostrar;
      if (subTip) subTip.textContent = idMostrar;

      if (
        (tipoNormalizado === "convencional" || tipoNormalizado.includes("convencional")) &&
        !tipoNormalizado.includes("no") &&
        offcanvasConvencional
      ) {
        bootstrap.Offcanvas.getOrCreateInstance(offcanvasConvencional).show();
        return;
      }

      if (
        (tipoNormalizado === "no_convencional" || tipoNormalizado.includes("no_convencional") || tipoNormalizado.includes("no convencional")) &&
        offcanvasNoConvencional
      ) {
        bootstrap.Offcanvas.getOrCreateInstance(offcanvasNoConvencional).show();
        return;
      }

      if ((tipoNormalizado === "tipologia" || tipoNormalizado.includes("tipolog")) && offcanvasTipologia) {
        bootstrap.Offcanvas.getOrCreateInstance(offcanvasTipologia).show();
        return;
      }

      if (offcanvasConvencional) {
        bootstrap.Offcanvas.getOrCreateInstance(offcanvasConvencional).show();
      }
    }

    function poblarOffcanvasConvencionalEdit(detalle = {}) {
      const car = detalle?.caracteristicas || {};
      const cal = detalle?.calificacion_convencional || {};

      setTextByIdEdit("convencionalTipoCalificacion", car?.tipo_calificacion_nombre || cal?.tipo_calificacion_nombre);
      setTextByIdEdit("convencionalTipoUnidad", car?.tipo_unidad_construccion_nombre);
      setTextByIdEdit("convencionalUso", car?.uso_nombre);
      setTextByIdEdit("convencionalTotalPlantas", car?.total_plantas);
      setTextByIdEdit("convencionalAnioConstruccion", car?.anio_construccion);
      setTextByIdEdit("convencionalAreaConstruida", car?.area_construida);
      setTextByIdEdit("convencionalAreaPrivadaConstruida", car?.area_privada_construida);
      setTextByIdEdit("convencionalUsosTradicionales", car?.usos_tradicionales_culturales_nombre ?? car?.usos_tradicionales_culturales);
      setTextByIdEdit("convencionalObservaciones", car?.observaciones);

      setTextByIdEdit("convencionalTipoCalificar", cal?.tipo_calificar_nombre);
      setTextByIdEdit("convencionalArmazon", cal?.armazon_nombre);
      setTextByIdEdit("convencionalMuros", cal?.muros_nombre);
      setTextByIdEdit("convencionalCubierta", cal?.cubierta_nombre);
      setTextByIdEdit("convencionalConservacionEstructura", cal?.conservacion_estructura_nombre);
      setTextByIdEdit("convencionalCubrimientoMuros", cal?.cubrimiento_muros_nombre);
      setTextByIdEdit("convencionalFachada", cal?.fachada_nombre);
      setTextByIdEdit("convencionalPiso", cal?.piso_nombre);
      setTextByIdEdit("convencionalConservacionAcabados", cal?.conservacion_acabados_nombre);
      setTextByIdEdit("convencionalTamanioBanio", cal?.tamanio_banio_nombre);
      setTextByIdEdit("convencionalEnchapeBanio", cal?.enchape_banio_nombre);
      setTextByIdEdit("convencionalMobiliarioBanio", cal?.mobiliario_banio_nombre);
      setTextByIdEdit("convencionalConservacionBanio", cal?.conservacion_banio_nombre);
      setTextByIdEdit("convencionalTamanioCocina", cal?.tamanio_cocina_nombre);
      setTextByIdEdit("convencionalEnchapeCocina", cal?.enchape_cocina_nombre);
      setTextByIdEdit("convencionalMobiliarioCocina", cal?.mobiliario_cocina_nombre);
      setTextByIdEdit("convencionalConservacionCocina", cal?.conservacion_cocina_nombre);
      setTextByIdEdit("convencionalCerchas", cal?.cerchas_complemento_industria_nombre ?? car?.cc_cerchas_complemento_industria);
      setTextByIdEdit("convencionalObsCalificacion", car?.observaciones);
      setTextByIdEdit("convencionalTotalCalificacion", cal?.total_calificacion);

      const chkAlturaCerchas = document.getElementById("convencionalAlturaCerchas");
      if (chkAlturaCerchas) {
        const raw = cal?.altura_cerchas_superior_6m;
        const normalized = String(raw ?? "").trim().toLowerCase();
        chkAlturaCerchas.checked = raw === true || normalized === "t" || normalized === "true" || normalized === "1" || normalized === "si" || normalized === "sí";
      }
    }

    function poblarOffcanvasNoConvencionalEdit(detalle = {}) {
      const car = detalle?.caracteristicas || {};
      const cal = detalle?.tipologia_no_convencional || {};

      setTextByIdEdit("noconvencionalTipoCalificacion", car?.tipo_calificacion_nombre || "No Convencional");
      setTextByIdEdit("noconvencionalTipoUnidad", car?.tipo_unidad_construccion_nombre);
      setTextByIdEdit("noconvencionalUso", car?.uso_nombre);
      setTextByIdEdit("noconvencionalTotalPlantas", car?.total_plantas);
      setTextByIdEdit("noconvencionalAnioConstruccion", car?.anio_construccion);
      setTextByIdEdit("noconvencionalAreaConstruida", car?.area_construida);
      setTextByIdEdit("noconvencionalAreaPrivadaConstruida", car?.area_privada_construida);
      setTextByIdEdit("noconvencionalUsosTradicionales", car?.usos_tradicionales_culturales_nombre ?? car?.usos_tradicionales_culturales);
      setTextByIdEdit("noconvencionalObservaciones", car?.observaciones);
      setTextByIdEdit("noconvencionalTipoAnexo", cal?.tipo_anexo_nombre);
      setTextByIdEdit("noconvencionalConservacionAnexo", cal?.conservacion_anexo_nombre);
    }

    function poblarOffcanvasTipologiaEdit(detalle = {}) {
      const car = detalle?.caracteristicas || {};
      const cal = detalle?.tipologia_construccion || {};

      setTextByIdEdit("tipologiaTipoCalificacion", car?.tipo_calificacion_nombre || "Por Tipología");
      setTextByIdEdit("tipologiaTipoUnidad", car?.tipo_unidad_construccion_nombre);
      setTextByIdEdit("tipologiaUso", car?.uso_nombre);
      setTextByIdEdit("tipologiaTotalPlantas", car?.total_plantas);
      setTextByIdEdit("tipologiaAnioConstruccion", car?.anio_construccion);
      setTextByIdEdit("tipologiaAreaConstruida", car?.area_construida);
      setTextByIdEdit("tipologiaAreaPrivadaConstruida", car?.area_privada_construida);
      setTextByIdEdit("tipologiaUsosTradicionales", car?.usos_tradicionales_culturales_nombre ?? car?.usos_tradicionales_culturales);
      setTextByIdEdit("tipologiaObservaciones", car?.observaciones);
      setTextByIdEdit("tipologiaTipoTipologia", cal?.tipo_tipologia_nombre);
      setTextByIdEdit("tipologiaConservacionTipologia", cal?.conservacion_nombre);
    }

    function setTextByIdEdit(id, value) {
      const el = document.getElementById(id);
      if (!el) return;
      el.textContent = normalizarTextoEdit(value);
    }

    function seleccionarConstruccionEdit(index) {
      const construccion = construccionesDataEdit[index];
      if (!construccion) return;

      construccionActivaEdit = index;
      actualizarBadgeConstruccionActivaEdit(construccion);

      const unidades = obtenerListaUnidadesConstruccionEdit(construccion);
      renderUnidadConstruccionCardEdit(unidades);
    }

    function cargarTablasConstruccionesYUcEdit(payload = {}) {
      const construcciones = Array.isArray(payload?.construcciones)
        ? payload.construcciones
        : Array.isArray(payload)
          ? payload
          : [];

      renderTablaConstruccionesEdit(construcciones);
      mostrarMensajeSinSeleccionUcEdit();
    }

    function valorVacioEdit(value) {
      return value === null || value === undefined || String(value).trim() === "";
    }

    function pickFromRowsEdit(rows, keys) {
      for (const row of rows) {
        if (!row || typeof row !== "object") continue;
        for (const key of keys) {
          if (row[key] !== undefined && row[key] !== null && String(row[key]).trim() !== "") {
            return row[key];
          }
        }
      }
      return null;
    }

    function setModalTextFieldEdit(id, value) {
      const el = document.getElementById(id);
      if (el) {
        el.textContent = (value !== null && value !== undefined && String(value).trim() !== "") ? value : "----";
      }
    }

    function asSiNoEdit(value) {
      if (value === true || String(value).toLowerCase() === "true" || String(value).toLowerCase() === "sí" || String(value).toLowerCase() === "si") return "Sí";
      if (value === false || String(value).toLowerCase() === "false" || String(value).toLowerCase() === "no") return "No";
      return "----";
    }

    function formatDateMaybeEdit(value) {
      if (!value) return "----";
      return fmtDate(value);
    }

    function nombreInteresadoEdit(item = {}) {
      const nombreCompuesto = [
        item.primer_nombre,
        item.segundo_nombre,
        item.primer_apellido,
        item.segundo_apellido
      ].filter(Boolean).join(" ");

      return item.nombre_completo || item.razon_social || nombreCompuesto || "---";
    }

    function limpiarModalInformacionPredioEdit() {
      const fields = [
        "modal_numero_predial_anterior", "modal_codigo_orip", "modal_matricula_inmobiliaria",
        "modal_estado_fmi", "modal_fecha_apertura_fmi", "modal_fecha_inscripcion_catastral",
        "modal_vigencia_actualizacion", "modal_area_registral", "modal_area_catastral_terreno",
        "modal_coeficiente_copropiedad", "modal_area_coeficiente_copropiedad", "modal_condicion_predio",
        "modal_tipo_predio", "modal_destinacion_economica", "modal_fecha_visita_predial",
        "modal_correo_visita", "modal_resultado_visita_predial", "modal_celular_visita",
        "modal_tipo_documento_atendio", "modal_domicilio_notificacion", "modal_numero_documento_atendio",
        "modal_autoriza_notificaciones", "modal_nombre_atendio", "modal_tipo_captura",
        "modal_juridico_nombre", "modal_beneficio_comunidades_indigenas", "modal_predio_matriz",
        "modal_control_calidad", "modal_comodato", "modal_cabida_linderos",
        "modal_observacion_juridica", "modal_valido_control_calidad"
      ];
      fields.forEach(id => setModalTextFieldEdit(id, "----"));
    }

    function construirInteresadosDesdeDerechosEdit(detalle = {}, numeroPredial = "") {
      const derechos = Array.isArray(detalle?.derechos) ? detalle.derechos : [];
      const agrupados = new Map();

      derechos.forEach((der) => {
        const intId = der.interesado_id || der.interesado_t_id;
        if (!intId) return;

        if (!agrupados.has(intId)) {
          agrupados.set(intId, {
            id: intId,
            primer_nombre: der.primer_nombre,
            segundo_nombre: der.segundo_nombre,
            primer_apellido: der.primer_apellido,
            segundo_apellido: der.segundo_apellido,
            nombre_completo: der.nombre_completo,
            razon_social: der.razon_social,
            sexo_nombre: der.sexo_nombre,
            tipo_persona_nombre: der.tipo_persona_nombre,
            tipo_documento_nombre: der.tipo_documento_nombre,
            documento_identidad: der.documento_identidad,
            cuota_participacion: der.cuota_participacion,
            fecha_inicio_tenencia: der.fecha_inicio_tenencia,
            tipo_derecho_nombre: der.tipo_derecho_nombre,
            posesion_ancestral_tradicional: der.posesion_ancestral_tradicional,
            descripcion_derecho: der.descripcion_derecho,
            tipo_fuente_administrativa_nombre: der.tipo_fuente_administrativa_nombre,
            numero_fuente: der.numero_fuente,
            ente_emisor: der.ente_emisor,
            oficina_origen: der.oficina_origen,
            nombre_escritura: der.nombre_escritura,
            ciudad_origen: der.ciudad_origen,
            shadow_disponibilidad: der.estado_disponibilidad_nombre,
            descripcion_fuente: der.descripcion_fuente,
            observacion_fuente_administrativa: der.observacion_fuente_administrativa,
            grupo_etnico_nombre: der.grupo_etnico_nombre,
            naturaleza_juridica_nombre: der.naturaleza_juridica_nombre,
            codigo_naturaleza_juridica: der.codigo_naturaleza_juridica,
            autorreconocimiento_etnico: der.autorreconocimiento_etnico,
            autorreconocimiento_campesino: der.autorreconocimiento_campesino,
            departamento_nombre: der.departamento_nombre,
            telefono: der.telefono,
            municipio_nombre: der.municipio_nombre,
            correo_electronico: der.correo_electronico,
            domicilio_notificacion: der.domicilio_notificacion,
            autoriza_notificacion_correo: der.autoriza_notificacion_correo,
            direccion_residencia: der.direccion_residencia,
          });
        }
      });

      return Array.from(agrupados.values());
    }

    function actualizarModalInformacionPredioEdit(predioListado = {}, detalle = {}, interesados = []) {
      const predio = (detalle && typeof detalle === "object" && detalle.predio) ? detalle.predio : {};
      const datosAdicionales = Array.isArray(detalle?.datos_adicionales) ? detalle.datos_adicionales : [];
      const contactoVisita = Array.isArray(detalle?.contacto_visita) ? detalle.contacto_visita : [];
      const datoAdicional = datosAdicionales[0] || {};
      const contacto = contactoVisita[0] || {};
      const primerInteresado = Array.isArray(interesados) && interesados.length ? interesados[0] : {};
      const sourcesPredio = [predio, predioListado, datoAdicional];
      const sourcesVisita = [datoAdicional, contacto, primerInteresado, predio];

      setModalTextFieldEdit("modal_numero_predial_anterior", pickFromRowsEdit(sourcesPredio, ["numero_predial_anterior", "numero_predial_ant"]));
      setModalTextFieldEdit("modal_codigo_orip", pickFromRowsEdit(sourcesPredio, ["codigo_orip"]));
      setModalTextFieldEdit("modal_matricula_inmobiliaria", pickFromRowsEdit(sourcesPredio, ["matricula_inmobiliaria", "fmi"]));
      setModalTextFieldEdit("modal_estado_fmi", pickFromRowsEdit(sourcesPredio, ["estado_fmi_nombre", "estado_fmi"]));
      setModalTextFieldEdit("modal_fecha_apertura_fmi", formatDateMaybeEdit(pickFromRowsEdit(sourcesPredio, ["fecha_apertura_fmi"])));
      setModalTextFieldEdit("modal_fecha_inscripcion_catastral", formatDateMaybeEdit(pickFromRowsEdit(sourcesPredio, ["fecha_inscripcion_catastral"])));
      setModalTextFieldEdit("modal_vigencia_actualizacion", pickFromRowsEdit(sourcesPredio, ["vigencia_actualizacion", "vigencia"]));
      setModalTextFieldEdit("modal_area_registral", pickFromRowsEdit(sourcesPredio, ["area_registral", "area_registral_m2"]));
      setModalTextFieldEdit("modal_area_catastral_terreno", pickFromRowsEdit(sourcesPredio, ["area_catastral_terreno", "area_terreno"]));
      setModalTextFieldEdit("modal_coeficiente_copropiedad", pickFromRowsEdit(sourcesPredio, ["coeficiente_copropiedad"]));
      setModalTextFieldEdit("modal_area_coeficiente_copropiedad", pickFromRowsEdit(sourcesPredio, ["area_coeficiente_copropiedad"]));
      setModalTextFieldEdit("modal_condicion_predio", pickFromRowsEdit(sourcesPredio, ["condicion_predio_nombre", "condicion_predio"]));
      setModalTextFieldEdit("modal_tipo_predio", pickFromRowsEdit(sourcesPredio, ["tipo_predio_nombre", "tipo_predio"]));
      setModalTextFieldEdit("modal_destinacion_economica", pickFromRowsEdit(sourcesPredio, ["destinacion_economica_nombre", "destinacion_economica"]));

      setModalTextFieldEdit("modal_fecha_visita_predial", formatDateMaybeEdit(pickFromRowsEdit(sourcesVisita, ["fecha_visita_predial", "fecha_visita"])));
      setModalTextFieldEdit("modal_correo_visita", pickFromRowsEdit(sourcesVisita, ["correo_visita", "correo_electronico"]));
      setModalTextFieldEdit("modal_resultado_visita_predial", pickFromRowsEdit(sourcesVisita, ["resultado_visita_predial_nombre", "resultado_visita_nombre", "resultado_visita_predial", "resultado_visita"]));
      setModalTextFieldEdit("modal_celular_visita", pickFromRowsEdit(sourcesVisita, ["celular_visita", "celular", "telefono"]));
      setModalTextFieldEdit("modal_tipo_documento_atendio", pickFromRowsEdit(sourcesVisita, ["tipo_documento_atendio_nombre", "tipo_documento_quien_atendio_nombre", "tipo_documento_atendio", "tipo_documento_quien_atendio"]));
      setModalTextFieldEdit("modal_domicilio_notificacion", pickFromRowsEdit(sourcesVisita, ["domicilio_notificacion"]));
      setModalTextFieldEdit("modal_numero_documento_atendio", pickFromRowsEdit(sourcesVisita, ["numero_documento_atendio", "numero_documento_quien_atendio"]));
      setModalTextFieldEdit("modal_autoriza_notificaciones", asSiNoEdit(pickFromRowsEdit(sourcesVisita, ["autoriza_notificaciones", "autoriza_notificacion_correo"])));
      setModalTextFieldEdit("modal_nombre_atendio", pickFromRowsEdit(sourcesVisita, ["nombre_atendio", "nombre_quien_atendio", "nombre_contacto", "nombres_apellidos_quien_atendio"]) || nombreInteresadoEdit(primerInteresado));
      setModalTextFieldEdit("modal_tipo_captura", pickFromRowsEdit(sourcesVisita, ["tipo_captura_nombre", "tipo_captura"]));

      setModalTextFieldEdit("modal_juridico_nombre", nombreInteresadoEdit(primerInteresado));
      setModalTextFieldEdit("modal_beneficio_comunidades_indigenas", asSiNoEdit(pickFromRowsEdit(sourcesPredio, ["beneficio_comunidades_indigenas", "beneficio_comunidad_indigena"])));
      setModalTextFieldEdit("modal_predio_matriz", pickFromRowsEdit(sourcesPredio, ["predio_matriz"]));
      setModalTextFieldEdit("modal_control_calidad", pickFromRowsEdit(sourcesPredio, ["control_calidad"]));
      setModalTextFieldEdit("modal_comodato", asSiNoEdit(pickFromRowsEdit(sourcesPredio, ["comodato"])));
      setModalTextFieldEdit("modal_cabida_linderos", pickFromRowsEdit(sourcesPredio, ["cabida_linderos"]));
      setModalTextFieldEdit("modal_observacion_juridica", pickFromRowsEdit(sourcesPredio, ["observacion_juridica"]));
      setModalTextFieldEdit("modal_valido_control_calidad", asSiNoEdit(pickFromRowsEdit(sourcesPredio, ["valido_control_calidad", "validado_control_calidad"])));
    }

    function obtenerNumeroPredialInteresadoEdit(item = {}) {
      return item.numero_predial_nacional || item.predio_numero_predial || "-";
    }

    function contarInteresadosPredioEdit(numeroPredial) {
      if (!numeroPredial || !Array.isArray(interesadosModalEditData)) {
        return 0;
      }
      return interesadosModalEditData.filter((item) =>
        String(obtenerNumeroPredialInteresadoEdit(item)) === String(numeroPredial)
      ).length;
    }

    function contarConstruccionesPredioEdit(numeroPredial) {
      if (!numeroPredial || !Array.isArray(construccionesDataEdit)) {
        return 0;
      }
      return construccionesDataEdit.filter((item) =>
        String(obtenerPredioConstruccionEdit(item)) === String(numeroPredial)
      ).length;
    }

    function limpiarResumenPredioEdit() {
      setText("resumenPredioOperacionId", "-");
      setText("resumenPredioNumero", "-");
      setText("resumenPredioInteresados", 0);
      setText("resumenPredioConstrucciones", 0);
      setText("resumenPredioUnidadConstruccion", 0);
      limpiarModalInformacionPredioEdit();
    }

    function resetDetallePredioEdit() {
      limpiarResumenPredioEdit();
      renderTablaConstruccionesEdit([]);
      renderInteresadosModalEdit([]);
      const badgeCountContainer = document.getElementById("badgeJuridicoCountContainer");
      if (badgeCountContainer) {
        badgeCountContainer.classList.add("d-none");
        badgeCountContainer.classList.remove("d-flex");
      }
    }

    function marcarResumenPredioCargandoEdit(predio = {}) {
      setText("resumenPredioOperacionId", predio?.predio_t_id ?? "-");
      setText("resumenPredioNumero", predio?.numero_predial_nacional ?? "-");
      setText("resumenPredioInteresados", "...");
      setText("resumenPredioConstrucciones", "...");
      setText("resumenPredioUnidadConstruccion", "...");
    }

    function agruparConstruccionesDesdeDetalleEdit(unidades = [], numeroPredial = "", construccionesRaw = []) {
      const normalizarUnidad = (unidad = {}, construccionId = null) => ({
        ...unidad,
        construccion_id: unidad?.construccion_id ?? unidad?.construccion_t_id ?? construccionId,
        identificador:
          unidad?.identificador ??
          unidad?.caracteristica_identificador ??
          unidad?.codigo ??
          unidad?.t_id ??
          "---",
        tipo_unidad_construccion_nombre:
          unidad?.tipo_unidad_construccion_nombre ??
          unidad?.tipo_calificacion_resumen ??
          unidad?.tipo_calificacion_clase ??
          "---",
      });

      if (Array.isArray(construccionesRaw) && construccionesRaw.length) {
        return construccionesRaw.map((c) => {
          const consId = c?.t_id ?? c?.id ?? null;
          const nestedUnits = Array.isArray(c?.unidades) ? c.unidades : [];
          const fallbackUnits = Array.isArray(unidades)
            ? unidades.filter((unidad) => String(unidad?.construccion_id ?? unidad?.construccion_t_id ?? "") === String(consId ?? ""))
            : [];
          const unidadesMap = new Map();

          [...nestedUnits, ...fallbackUnits].forEach((unidad) => {
            const normalizada = normalizarUnidad(unidad, consId);
            const key = String(normalizada?.t_id ?? normalizada?.unidad_id ?? normalizada?.id ?? `${consId}-${unidadesMap.size}`);
            if (!unidadesMap.has(key)) {
              unidadesMap.set(key, normalizada);
            }
          });

          return {
            id: consId,
            t_id: consId,
            identificador: c?.identificador || c?.etiqueta || consId,
            tipo_construccion_nombre: c?.tipo_construccion_nombre,
            predio_numero_predial: c?.numero_predial_nacional || c?.predio_numero_predial || numeroPredial,
            tipo_dominio_nombre: c?.tipo_dominio_nombre,
            total_mezaninis: c?.total_mezaninis,
            etiqueta: c?.etiqueta,
            total_pisos: c?.total_pisos,
            total_semisotanos: c?.total_semisotanos,
            estado_construccion_nombre: c?.estado_construccion_nombre,
            total_sotanos: c?.total_sotanos,
            area_total_construccion: c?.area_total_construccion,
            observacion: c?.observacion,
            unidades: Array.from(unidadesMap.values()),
          };
        });
      }

      const grupos = new Map();
      unidades.forEach((unidad) => {
        const consId = unidad?.construccion_id || unidad?.construccion_t_id;
        if (!consId) return;
        const consKey = String(consId);

        if (!grupos.has(consKey)) {
          grupos.set(consKey, {
            id: consId,
            t_id: consId,
            identificador: unidad?.construccion_identificador || unidad?.identificador || consId,
            tipo_construccion_nombre: unidad?.tipo_construccion_nombre,
            predio_numero_predial: unidad?.predio_numero_predial || numeroPredial,
            tipo_dominio_nombre: unidad?.tipo_dominio_nombre,
            total_mezaninis: unidad?.total_mezaninis,
            etiqueta: unidad?.etiqueta,
            total_pisos: unidad?.total_pisos,
            total_semisotanos: unidad?.total_semisotanos,
            estado_construccion_nombre: unidad?.estado_construccion_nombre,
            total_sotanos: unidad?.total_sotanos,
            area_total_construccion: unidad?.area_total_construccion,
            observacion: unidad?.observacion,
            unidades: [],
          });
        }

        const grupo = grupos.get(consKey);
        const normalizada = normalizarUnidad(unidad, consId);
        const unitKey = String(normalizada?.t_id ?? normalizada?.unidad_id ?? normalizada?.id ?? "");
        const yaExiste = Array.isArray(grupo?.unidades) && grupo.unidades.some((item) => {
          const itemKey = String(item?.t_id ?? item?.unidad_id ?? item?.id ?? "");
          return unitKey && itemKey === unitKey;
        });

        if (!yaExiste) {
          grupo.unidades.push(normalizada);
        }
      });

      return Array.from(grupos.values());
    }

    function invalidarCachesDetalleAsignacion() {
      detallePredioCacheDetail = new Map();
      detallePredioCacheEdit = new Map();
      unidadDetalleCacheEdit = new Map();
      detallePredioActualEdit = null;
      unidadDetalleActualEdit = null;
    }

    async function aplicarDetallePredioSeleccionadoEdit(predio, detalle = {}) {
      const numeroPredial = predio?.numero_predial_nacional || detalle?.predio?.numero_predial_nacional || "-";
      const interesadosRaw = Array.isArray(detalle?.interesados)
        ? detalle.interesados
        : [];
      const interesados = (interesadosRaw.length ? interesadosRaw : construirInteresadosDesdeDerechosEdit(detalle, numeroPredial))
        .map((item) => ({
          ...item,
          numero_predial_nacional:
            item?.numero_predial_nacional ||
            item?.predio_numero_predial ||
            numeroPredial,
        }));
      const construcciones = agruparConstruccionesDesdeDetalleEdit(
        Array.isArray(detalle?.unidades_construccion) ? detalle.unidades_construccion : [],
        numeroPredial,
        Array.isArray(detalle?.construcciones) ? detalle.construcciones : []
      );

      setText("resumenPredioOperacionId", predio?.predio_t_id ?? detalle?.predio?.t_id ?? "-");
      setText("resumenPredioNumero", numeroPredial);
      setText("resumenPredioInteresados", interesados.length);
      setText("resumenPredioConstrucciones", construcciones.length);
      setText(
        "resumenPredioUnidadConstruccion",
        construcciones.reduce((acc, item) => acc + contarUcAsociadasEdit(item), 0)
      );

      detallePredioActualEdit = detalle;
      actualizarModalInformacionPredioEdit(predio, detalle, interesados);
      renderInteresadosModalEdit(interesados);
      cargarTablasConstruccionesYUcEdit({ construcciones });

      // Badge de cantidad de interesados en Información Jurídica
      const badgeCountValue = document.getElementById("badgeJuridicoCountValue");
      const badgeCountContainer = document.getElementById("badgeJuridicoCountContainer");
      if (badgeCountValue && badgeCountContainer) {
        badgeCountValue.textContent = interesados.length;
        if (interesados.length > 0) {
          badgeCountContainer.classList.remove("d-none");
          badgeCountContainer.classList.add("d-flex");
        } else {
          badgeCountContainer.classList.add("d-none");
          badgeCountContainer.classList.remove("d-flex");
        }
      }
    }

    function setPanelTextEdit(id, value) {
      const el = document.getElementById(id);
      if (el) {
        el.textContent = value ?? "---";
      }
    }

    function construirNombreInteresadoEdit(item = {}) {
      const nombreCompuesto = [
        item.primer_nombre,
        item.segundo_nombre,
        item.primer_apellido,
        item.segundo_apellido
      ].filter(Boolean).join(" ");

      return item.nombre_completo || item.razon_social || nombreCompuesto || "---";
    }

    function verInformacionCompletaInteresadoEdit(index) {
      const item = interesadosModalEditData[index];
      if (!item) return;

      setPanelTextEdit("nombreInteresadoPanelEdit", construirNombreInteresadoEdit(item));

      /* informacion de derechos */
      setPanelTextEdit("panel_fecha_inicio_tenencia_edit", item.fecha_inicio_tenencia || "---");
      setPanelTextEdit("panel_tipo_derecho_edit", item.tipo_derecho_nombre || item.tipo_derecho || "---");
      setPanelTextEdit("panel_posesion_ancestral_edit", asSiNoEdit(item.posesion_ancestral_tradicional));
      setPanelTextEdit("panel_descripcion_derecho_edit", item.descripcion_derecho || "---");

      /* informacion fuente administrativa */
      setPanelTextEdit("panel_tipo_fuente_admin_edit", item.tipo_fuente_administrativa_nombre || item.tipo_fuente_administrativa || "---");
      setPanelTextEdit("panel_numero_fuente_edit", item.numero_fuente || "---");
      setPanelTextEdit("panel_ente_emisor_edit", item.ente_emisor || "---");
      setPanelTextEdit("panel_oficina_origen_edit", item.oficina_origen || "---");
      setPanelTextEdit("panel_nombre_escritura_edit", item.nombre_escritura || "---");
      setPanelTextEdit("panel_ciudad_origen_edit", item.ciudad_origen || "---");
      setPanelTextEdit("panel_estado_disponibilidad_edit", item.estado_disponibilidad_nombre || item.estado_disponibilidad || "---");
      setPanelTextEdit("panel_descripcion_fuente_edit", item.descripcion_fuente || "---");
      setPanelTextEdit("panel_observacion_fuente_edit", item.observacion_fuente_administrativa || "---");

      const modalEl = document.getElementById("modalInformacionAdicional");
      const offcanvasEl = document.getElementById("panelDerechoPredioEdit");

      if (modalEl) {
        const modalInstance = bootstrap.Modal.getInstance(modalEl);
        if (modalInstance) {
          modalInstance.hide();
        }
      }

      if (offcanvasEl) {
        const offcanvasInstance = bootstrap.Offcanvas.getOrCreateInstance(offcanvasEl);
        offcanvasInstance.show();
      }
    }

    function renderInteresadosModalEdit(interesadosRaw) {
      const tbody = document.getElementById("tbodyModalInteresadosEdit");
      if (!tbody) return;

      if (!interesadosRaw || !interesadosRaw.length) {
        tbody.innerHTML = `
              <tr>
                  <td colspan="5" class="text-center text-muted py-4">
                      No hay información jurídica disponible.
                  </td>
              </tr>
          `;
        return;
      }

      const interesados = interesadosRaw.map((i) => {
        const nombreCompuesto = [
          i.primer_nombre,
          i.segundo_nombre,
          i.primer_apellido,
          i.segundo_apellido,
        ].filter(Boolean).join(" ");

        const nombreMostrar =
          i.nombre_completo ||
          i.razon_social ||
          nombreCompuesto ||
          "---";

        const partesNombre = nombreMostrar.trim().split(/\s+/);
        const linea1 = partesNombre.slice(0, 2).join(" ") || nombreMostrar;
        const linea2 = partesNombre.slice(2).join(" ");

        const sexo = i.sexo_nombre || i.sexo || "---";

        const cuotaBase =
          i.cuota_participacion ??
          i.porcentaje_participacion ??
          i.fraccion ??
          "---";

        const cuotaTexto =
          cuotaBase !== "---" && !String(cuotaBase).includes("%")
            ? `${cuotaBase} %`
            : String(cuotaBase);

        const tipoPersona =
          i.tipo_persona_nombre ||
          i.tipo_persona ||
          (i.razon_social ? "Persona Jurídica" : "Persona Natural");

        return {
          ...i,
          linea1,
          linea2,
          sexo,
          cuotaTexto,
          tipoPersona
        };
      });

      interesadosModalEditData = interesados;

      tbody.innerHTML = interesados.map((item, index) => {
        const autorizaNotif = item.autoriza_notificacion_correo === true || item.autoriza_notificacion_correo === 'true' || item.autoriza_notificacion_correo === 't' ? 'Sí' :
          (item.autoriza_notificacion_correo === false || item.autoriza_notificacion_correo === 'false' || item.autoriza_notificacion_correo === 'f' ? 'No' : '---');

        const campesinoTexto = item.autorreconocimiento_campesino === true || item.autorreconocimiento_campesino === 'true' || item.autorreconocimiento_campesino === 't' ? 'Sí' :
          (item.autorreconocimiento_campesino === false || item.autorreconocimiento_campesino === 'false' || item.autorreconocimiento_campesino === 'f' ? 'No' : '---');

        const etnicoTexto = item.autorreconocimiento_etnico === true || item.autorreconocimiento_etnico === 'true' || item.autorreconocimiento_etnico === 't' ? 'Sí' :
          (item.autorreconocimiento_etnico === false || item.autorreconocimiento_etnico === 'false' || item.autorreconocimiento_etnico === 'f' ? 'No' : '---');

        return `
            <tr class="fila-interesado-principal-edit" data-detalle-id="detalleInteresadoEdit_${index}">
                <td>
                    <div class="d-flex align-items-center gap-3">
                        <div class="icono-interesado-circle-edit">
                            <i class="fa-solid fa-user"></i>
                        </div>
                        <div class="info-interesado-nombre-edit">
                            <div>${item.linea1 || "---"}</div>
                            <div>${item.linea2 || ""}</div>
                        </div>
                    </div>
                </td>

                <td class="columna-con-linea-edit">
                    <span class="texto-tabla-interesado-edit fw-semibold">${item.sexo || "---"}</span>
                </td>

                <td>
                    <span class="badge-cuota-participacion-edit">${item.cuotaTexto || "---"}</span>
                </td>

                <td>
                    <span class="texto-tabla-interesado-edit">${item.tipoPersona || "---"}</span>
                </td>

                <td class="text-center">
                    <button
                        type="button"
                        class="btn-detalle-tabla-edit border-0 bg-transparent"
                        data-bs-toggle="collapse"
                        data-bs-target="#detalleInteresadoEdit_${index}"
                        aria-expanded="false"
                        aria-controls="detalleInteresadoEdit_${index}"
                    >
                        <i class="fa-solid fa-chevron-down"></i>
                    </button>
                </td>
            </tr>

            <tr class="fila-detalle-interesado-edit">
                <td colspan="5" class="p-0 border-0">
                    <div class="collapse" id="detalleInteresadoEdit_${index}">
                        <div class="detalle-interesado-contenido-edit">
                            <div class="tarjet-infop-edit d-inline-block w-50 px-3 py-2 rounded-3">
                                <div class="text-center mb-0 text-infort-edit">Información personal</div>
                            </div>

                            <div class="row mt-4 w-100 mx-0">
                                <div class="col-12 col-md-6 pe-md-5">
                                    <div class="row g-3">
                                        <div class="col-12">
                                            <div class="d-flex justify-content-between align-items-center w-100">
                                                <div class="text-start text-lojh-edit mb-0">Tipo de documento</div>
                                                <div class="text-end mb-0">${item.tipo_documento_nombre || "---"}</div>
                                            </div>
                                        </div>

                                        <div class="col-12 mt-4">
                                            <div class="d-flex justify-content-between align-items-center w-100">
                                                <div class="text-start text-lojh-edit mb-0">Documento de identidad</div>
                                                <div class="text-end mb-0">${item.documento_identidad || "---"}</div>
                                            </div>
                                        </div>

                                        <div class="col-12">
                                            <div class="d-flex justify-content-between align-items-center w-100">
                                                <div class="text-start text-lojh-edit mb-0">Grupo étnico</div>
                                                <div class="text-end mb-0">${item.grupo_etnico_nombre || "---"}</div>
                                            </div>
                                        </div>

                                        <div class="col-12 mt-4">
                                            <div class="d-flex justify-content-between align-items-center w-100">
                                                <div class="text-start text-lojh-edit mb-0">Razón social</div>
                                                <div class="text-end mb-0">${item.razon_social || "---"}</div>
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                <div class="col-12 col-md-6 ps-md-5">
                                    <div class="row g-3">
                                        <div class="col-12">
                                            <div class="d-flex justify-content-between align-items-center w-100">
                                                <div class="text-start text-lojh-edit mb-0">Naturaleza jurídica</div>
                                                <div class="text-end mb-0">${item.naturaleza_juridica_nombre || "---"}</div>
                                            </div>
                                        </div>

                                        <div class="col-12 mt-4">
                                            <div class="d-flex justify-content-between align-items-center w-100">
                                                <div class="text-start text-lojh-edit mb-0">Autorreconocimiento étnico</div>
                                                <div class="text-end mb-0">${etnicoTexto}</div>
                                            </div>
                                        </div>

                                        <div class="col-12 mt-4">
                                            <div class="d-flex justify-content-between align-items-center w-100">
                                                <div class="text-start text-lojh-edit mb-0">Código naturaleza jurídica</div>
                                                <div class="text-end mb-0">${item.codigo_naturaleza_juridica || "---"}</div>
                                            </div>
                                        </div>

                                        <div class="col-12 mt-4">
                                            <div class="d-flex justify-content-between align-items-center w-100">
                                                <div class="text-start text-lojh-edit mb-0">Autorreconocimiento campesino</div>
                                                <div class="text-end mb-0">${campesinoTexto}</div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div class="tarjet-infop-edit d-inline-block w-50 px-3 py-2 rounded-3 mt-4">
                                <div class="text-center mb-0 text-infort-edit">Información de contacto</div>
                            </div>

                            <div class="row mt-4 w-100 mx-0">
                                <div class="col-12 col-md-6 pe-md-5">
                                    <div class="row g-3">
                                        <div class="col-12">
                                            <div class="d-flex justify-content-between align-items-center w-100">
                                                <div class="text-start text-lojh-edit mb-0">Departamento</div>
                                                <div class="text-end mb-0">${item.departamento_nombre || "---"}</div>
                                            </div>
                                        </div>

                                        <div class="col-12 mt-4">
                                            <div class="d-flex justify-content-between align-items-center w-100">
                                                <div class="text-start text-lojh-edit mb-0">Teléfono</div>
                                                <div class="text-end mb-0">${item.telefono || "---"}</div>
                                            </div>
                                        </div>

                                        <div class="col-12 mt-4">
                                            <div class="d-flex justify-content-between align-items-center w-100">
                                                <div class="text-start text-lojh-edit mb-0">Municipio</div>
                                                <div class="text-end mb-0">${item.municipio_nombre || "---"}</div>
                                            </div>
                                        </div>

                                        <div class="col-12 mt-4">
                                            <div class="d-flex justify-content-between align-items-center w-100">
                                                <div class="text-start text-lojh-edit mb-0">Correo electrónico</div>
                                                <div class="text-end mb-0">${item.correo_electronico || "---"}</div>
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                <div class="col-12 col-md-6 ps-md-5">
                                    <div class="row g-3">
                                        <div class="col-12">
                                            <div class="d-flex justify-content-between align-items-center w-100">
                                                <div class="text-start text-lojh-edit mb-0">Domicilio de notificación</div>
                                                <div class="text-end mb-0">${item.domicilio_notificacion || "---"}</div>
                                            </div>
                                        </div>

                                        <div class="col-12 mt-4">
                                            <div class="d-flex justify-content-between align-items-center w-100">
                                                <div class="text-start text-lojh-edit mb-0">¿Autoriza notificación por correo?</div>
                                                <div class="text-end mb-0">${autorizaNotif}</div>
                                            </div>
                                        </div>

                                        <div class="col-12 mt-4">
                                            <div class="d-flex justify-content-between align-items-center w-100">
                                                <div class="text-start text-lojh-edit mb-0">Dirección de residencia</div>
                                                <div class="text-end mb-0">${item.direccion_residencia || "---"}</div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div class="d-flex justify-content-end mt-4">
                                <button
                                    type="button"
                                    class="btn-gunmi-edit d-inline-flex align-items-center gap-2"
                                    onclick="verInformacionCompletaInteresadoEdit(${index})"
                                >
                                    <i class="fa-solid fa-arrow-right"></i>
                                    <span>Ver información completa</span>
                                </button>
                            </div>
                        </div>
                    </div>
                </td>
            </tr>
        `;
      }).join("");

      tbody.querySelectorAll(".collapse").forEach((collapseEl) => {
        collapseEl.addEventListener("show.bs.collapse", () => {
          tbody.querySelectorAll(".collapse.show").forEach((openEl) => {
            if (openEl.id !== collapseEl.id) {
              const openInstance = bootstrap.Collapse.getOrCreateInstance(openEl, { toggle: false });
              openInstance.hide();
            }
          });

          tbody.querySelectorAll(".fila-interesado-principal-edit").forEach((row) => {
            row.classList.remove("fila-interesado-activa-edit");
            const icon = row.querySelector(".btn-detalle-tabla-edit i");
            if (icon) icon.classList.remove("rotate-180");
          });

          tbody.querySelectorAll(".fila-detalle-interesado-edit").forEach((row) => {
            row.classList.remove("fila-detalle-interesado-activa-edit");
          });

          tbody.querySelectorAll(".detalle-interesado-contenido-edit").forEach((box) => {
            box.classList.remove("detalle-interesado-contenido-activo-edit");
          });

          const detailRow = collapseEl.closest(".fila-detalle-interesado-edit");
          const principalRow = detailRow?.previousElementSibling;
          const detailBox = collapseEl.querySelector(".detalle-interesado-contenido-edit");

          if (principalRow) {
            principalRow.classList.add("fila-interesado-activa-edit");
            const icon = principalRow.querySelector(".btn-detalle-tabla-edit i");
            if (icon) icon.classList.add("rotate-180");
          }

          if (detailRow) {
            detailRow.classList.add("fila-detalle-interesado-activa-edit");
          }

          if (detailBox) {
            detailBox.classList.add("detalle-interesado-contenido-activo-edit");
          }
        });

        collapseEl.addEventListener("hide.bs.collapse", () => {
          const detailRow = collapseEl.closest(".fila-detalle-interesado-edit");
          const principalRow = detailRow?.previousElementSibling;
          const detailBox = collapseEl.querySelector(".detalle-interesado-contenido-edit");

          if (principalRow) {
            principalRow.classList.remove("fila-interesado-activa-edit");
            const icon = principalRow.querySelector(".btn-detalle-tabla-edit i");
            if (icon) icon.classList.remove("rotate-180");
          }

          if (detailRow) {
            detailRow.classList.remove("fila-detalle-interesado-activa-edit");
          }

          if (detailBox) {
            detailBox.classList.remove("detalle-interesado-contenido-activo-edit");
          }
        });
      });
    }