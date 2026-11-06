/**
 * render_workarea_audio.jsx
 * 
 * Exports uncompressed audio from the active composition's Work Area (shortcuts B & N).
 * Outputs:
 * - Audio file: /tmp/ae_workarea_audio.aif
 * - Metadata JSON: /tmp/ae_workarea_meta.json
 */

(function renderWorkAreaAudio() {
    if (!app.project) {
        return "ERROR: No active After Effects project.";
    }

    var comp = app.project.activeItem;
    if (!comp || !(comp instanceof CompItem)) {
        return "ERROR: No active composition selected. Please open or click a composition timeline.";
    }

    var workStart = comp.workAreaStart;
    var workDuration = comp.workAreaDuration;

    if (workDuration <= 0) {
        return "ERROR: Work Area duration is 0 seconds.";
    }

    var audioFile = new File("/tmp/ae_workarea_audio.aif");
    if (audioFile.exists) {
        try { audioFile.remove(); } catch(e) {}
    }

    var rq = app.project.renderQueue;
    var item = rq.items.add(comp);

    // Render ONLY the Work Area range natively via Current Settings
    try {
        item.applyTemplate("Current Settings");
    } catch(e) {}

    // Apply native AIFF uncompressed audio template
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
        // Fallback to first template
        om.applyTemplate(om.templates[0]);
    }

    om.file = audioFile;

    // Execute render with dialog suppression
    app.beginSuppressDialogs();
    try {
        rq.render();
    } catch(err) {
        app.endSuppressDialogs(false);
        item.remove();
        return "ERROR: Render failed: " + err.toString();
    }
    app.endSuppressDialogs(false);

    // Clean up render queue item
    item.remove();

    if (!audioFile.exists || audioFile.length <= 0) {
        return "ERROR: Rendered audio file was not created.";
    }

    var timelineOffset = workStart;

    // Write metadata JSON
    var metaFile = new File("/tmp/ae_workarea_meta.json");
    metaFile.open("w");
    metaFile.encoding = "UTF-8";
    var metaObj = {
        "comp_name": comp.name,
        "comp_width": comp.width,
        "comp_height": comp.height,
        "work_area_start": timelineOffset,
        "work_area_duration": workDuration,
        "audio_file": audioFile.fsName
    };
    
    // JSON stringify fallback
    var metaStr = "";
    if (typeof JSON !== "undefined" && JSON.stringify) {
        metaStr = JSON.stringify(metaObj);
    } else {
        metaStr = '{"comp_name":"' + comp.name.replace(/"/g, '\\"') + '","work_area_start":' + timelineOffset + ',"work_area_duration":' + workDuration + ',"audio_file":"' + audioFile.fsName.replace(/\\/g, '\\\\') + '"}';
    }
    metaFile.write(metaStr);
    metaFile.close();

    return "SUCCESS:" + timelineOffset + ":" + workDuration;
})();
