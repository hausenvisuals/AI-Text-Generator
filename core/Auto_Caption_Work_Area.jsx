/**
 * Auto_Caption_Work_Area.jsx
 * 
 * 1-Click Automated Captioning directly inside Adobe After Effects!
 * 
 * Workflow:
 * 1. Reads the Work Area (B & N) from the active timeline.
 * 2. Prompts user to select Caption Grouping Mode (Single Word / Short / Long).
 * 3. Renders Work Area audio automatically.
 * 4. Calls Python AI pipeline (ElevenLabs STT + OpenAI Grouping).
 * 5. Creates accurately positioned, styled text layers at the Work Area timeline position.
 */

(function autoCaptionWorkArea() {
    if (!app.project) {
        alert("Please open an After Effects project first.", "No Project");
        return;
    }

    var comp = app.project.activeItem;
    if (!comp || !(comp instanceof CompItem)) {
        alert("Please open and select a composition timeline in After Effects.", "No Active Comp");
        return;
    }

    var workStart = comp.workAreaStart;
    var workDuration = comp.workAreaDuration;

    if (workDuration <= 0) {
        alert("Work Area duration is 0 seconds. Please mark an area using shortcuts B and N.", "Invalid Work Area");
        return;
    }

    var timelineOffset = workStart;

    // Helper: format seconds to MM:SS.mmm
    function fmtTime(sec) {
        var m = Math.floor(sec / 60);
        var s = (sec % 60).toFixed(2);
        return (m < 10 ? "0" : "") + m + ":" + (parseFloat(s) < 10 ? "0" : "") + s;
    }

    // 1. ScriptUI Dialog
    var dlg = new Window("dialog", "AI Caption Generator - Work Area");
    dlg.orientation = "column";
    dlg.alignChildren = ["fill", "top"];
    dlg.spacing = 12;
    dlg.margins = 18;

    // Header Info
    var pnl = dlg.add("panel", undefined, "Active Composition & Timeline Range");
    pnl.orientation = "column";
    pnl.alignChildren = ["left", "top"];
    pnl.spacing = 6;
    pnl.margins = 12;

    pnl.add("statictext", undefined, "Composition: " + comp.name);
    pnl.add("statictext", undefined, "Work Area: " + fmtTime(workStart) + " ➔ " + fmtTime(workStart + workDuration) + " (" + workDuration.toFixed(2) + "s)");

    // Mode Selector
    var modePnl = dlg.add("panel", undefined, "Caption Grouping Mode");
    modePnl.orientation = "column";
    modePnl.alignChildren = ["fill", "top"];
    modePnl.margins = 12;

    var modeDropdown = modePnl.add("dropdownlist", undefined, ["Single Word (1 kata per layer)", "Short (2-3 kata per layer - Default)", "Long (4-5 kata per layer)"]);
    modeDropdown.selection = 0; // Default to Single Word or 1

    var descText = modePnl.add("statictext", undefined, "Tepat 1 kata per layer. Dinamis untuk TikTok/Reels.");
    descText.graphics.foregroundColor = descText.graphics.newPen(descText.graphics.PenType.SOLID_COLOR, [0.4, 0.4, 0.4], 1);

    modeDropdown.onChange = function() {
        if (modeDropdown.selection.index === 0) {
            descText.text = "Tepat 1 kata per layer. Dinamis untuk TikTok/Reels.";
        } else if (modeDropdown.selection.index === 1) {
            descText.text = "Target 2-3 kata per grup. Natural dan mudah dibaca.";
        } else {
            descText.text = "Target 4-5 kata per grup. Format kalimat lengkap.";
        }
    };

    // Action Buttons
    var btnGroup = dlg.add("group");
    btnGroup.alignment = "right";
    var cancelBtn = btnGroup.add("button", undefined, "Batal");
    var okBtn = btnGroup.add("button", undefined, "🚀 Generate Captions", { name: "ok" });

    cancelBtn.onClick = function() { dlg.close(); };

    if (dlg.show() !== 1) {
        return;
    }

    var selectedModeStr = "single";
    if (modeDropdown.selection.index === 1) selectedModeStr = "short";
    if (modeDropdown.selection.index === 2) selectedModeStr = "long";

    // 2. Render Work Area Audio
    var audioFile = new File("/tmp/ae_workarea_audio.aif");
    if (audioFile.exists) {
        try { audioFile.remove(); } catch(e) {}
    }

    var rq = app.project.renderQueue;
    var item = rq.items.add(comp);
    try {
        item.applyTemplate("Current Settings");
    } catch(e) {}

    var om = item.outputModule(1);
    var applied = false;
    for (var i = 0; i < om.templates.length; i++) {
        var tName = om.templates[i];
        if (tName.indexOf("AIFF") !== -1 || tName.indexOf("WAV") !== -1 || tName.indexOf("Audio") !== -1) {
            om.applyTemplate(tName);
            applied = true;
            break;
        }
    }
    if (!applied) {
        om.applyTemplate(om.templates[0]);
    }
    om.file = audioFile;

    app.beginSuppressDialogs();
    try {
        rq.render();
    } catch(err) {
        app.endSuppressDialogs(false);
        item.remove();
        alert("Gagal merender audio dari After Effects:\n" + err.toString(), "Render Error");
        return;
    }
    app.endSuppressDialogs(false);
    item.remove();

    if (!audioFile.exists || audioFile.length <= 0) {
        alert("File audio Work Area tidak berhasil dibuat.", "Audio Export Error");
        return;
    }

    // 3. Call Python Pipeline in Background
    var scriptFolder = (new File($.fileName)).parent.fsName;
    var mainPy = scriptFolder + "/main.py";
    var cmd = 'python3 "' + mainPy + '" --input "' + audioFile.fsName + '" --mode ' + selectedModeStr + ' --time-offset ' + timelineOffset + ' --auto-import';

    var res = "";
    try {
        res = system.callSystem(cmd);
    } catch(callErr) {
        alert("After Effects memblokir eksekusi skrip eksternal.\n\nSilakan aktifkan:\nPreferences > Scripting & Expressions > 'Allow Scripts to Write Files and Access Network'\n\nAtau gunakan tombol di Web UI (python3 ui.py)!", "Permission Required");
        return;
    }

    // 4. If auto-import ran via system.callSystem, AE is already populated!
    // Refresh display
    app.activeViewer.setActive();

})();
