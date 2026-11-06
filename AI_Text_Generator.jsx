/**
 * AI_Text_Generator.jsx
 * 
 * Dockable ScriptUI Panel for Adobe After Effects.
 * 
 * Features:
 * 1. EXPORT: Renders Work Area audio & auto-segments captions into Kinetic Typography chunks.
 * 2. REVIEW & EDIT: Table displays master transcript. Edit phrasing & timing without losing original.
 * 3. IMPORT: 
 *    - Original Language: Creates master text layers directly in timeline.
 *    - Translation (ID/EN): Translates in background and directly imports layers into timeline
 *      WITHOUT mutating/overwriting the master table in the panel!
 */

(function buildAITextGeneratorPanel(thisObj) {
    var SCRIPT_NAME = "AI Text Generator";
    var loadedCaptions = [];
    var currentMode = "Long";
    var currentTimeOffset = 0.0;

    function getScriptFolder() {
        var SECTION_NAME = "AITextGenerator";
        var KEY_NAME = "CoreEnginePath";

        // 1. Cek folder 'core' yang berada berdampingan dengan file script saat ini
        try {
            if ($.fileName) {
                var f = new File($.fileName);
                var baseDir = f.parent.fsName;
                if (new File(baseDir + "/core/main.py").exists) {
                    return baseDir + "/core";
                }
                if (new File(baseDir + "/main.py").exists) {
                    return baseDir;
                }
            }
        } catch(e) {}

        // 2. Cek lokasi tersimpan sebelumnya di After Effects Settings
        try {
            if (app.settings.haveSetting(SECTION_NAME, KEY_NAME)) {
                var savedPath = app.settings.getSetting(SECTION_NAME, KEY_NAME);
                if (savedPath) {
                    if (new File(savedPath + "/main.py").exists) {
                        return savedPath;
                    }
                    if (new File(savedPath + "/core/main.py").exists) {
                        return savedPath + "/core";
                    }
                }
            }
        } catch(e) {}

        // 3. Cek lokasi workspace asli & folder umum pengguna (Documents, Downloads, Desktop)
        var userHome = "";
        try {
            userHome = Folder("~").fsName;
        } catch(e) {
            userHome = "";
        }

        var candidates = [
            "/Users/alfonrenaldo/Documents/antigravity/AE text automation plugins/AI_Text_Generator/core",
            userHome + "/Documents/antigravity/AE text automation plugins/AI_Text_Generator/core",
            "/Users/alfonrenaldo/Documents/antigravity/AE text automation plugins/core",
            userHome + "/Documents/antigravity/AE text automation plugins/core",
            userHome + "/Documents/AI_Text_Generator_for_Editor/core",
            userHome + "/Documents/AI_Text_Generator/core",
            userHome + "/Downloads/AI_Text_Generator_for_Editor/core",
            userHome + "/Downloads/AI_Text_Generator_for_Editor/AI_Text_Generator_for_Editor/core",
            userHome + "/Desktop/AI_Text_Generator_for_Editor/core",
            Folder.myDocuments.fsName + "/AI_Text_Generator_for_Editor/core",
            Folder.myDocuments.fsName + "/core",
            Folder.desktop.fsName + "/AI_Text_Generator_for_Editor/core",
            Folder.desktop.fsName + "/core"
        ];

        for (var i = 0; i < candidates.length; i++) {
            try {
                if (candidates[i] && new File(candidates[i] + "/main.py").exists) {
                    try {
                        app.settings.saveSetting(SECTION_NAME, KEY_NAME, candidates[i]);
                    } catch(err) {}
                    return candidates[i];
                }
            } catch(e) {}
        }

        // 4. Default fallback: di samping file JSX
        try {
            if ($.fileName) {
                var f2 = new File($.fileName);
                return f2.parent.fsName;
            }
        } catch(e) {}

        return Folder.myDocuments.fsName;
    }

    function getPythonBinary() {
        var isWin = ($.os.indexOf("Windows") !== -1);
        if (isWin) return "python";

        // Di macOS, utamakan binary python3 yang ada di sistem / Homebrew / CommandLineTools
        var candidates = [
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/Library/Developer/CommandLineTools/usr/bin/python3",
            "/usr/bin/python3"
        ];
        for (var i = 0; i < candidates.length; i++) {
            var f = new File(candidates[i]);
            if (f.exists) {
                return candidates[i];
            }
        }
        return "python3";
    }

    function formatTime(sec) {
        var s = parseFloat(sec);
        if (isNaN(s)) return "0.00";
        return s.toFixed(2);
    }

    function formatSrtTime(seconds) {
        var s = Math.max(0, parseFloat(seconds) || 0);
        var hrs = Math.floor(s / 3600);
        var mins = Math.floor((s % 3600) / 60);
        var secs = Math.floor(s % 60);
        var millis = Math.floor((s - Math.floor(s)) * 1000 + 0.5);
        if (millis >= 1000) {
            millis = 0;
            secs += 1;
        }

        function pad(n, z) {
            var str = "" + n;
            while (str.length < z) str = "0" + str;
            return str;
        }
        return pad(hrs, 2) + ":" + pad(mins, 2) + ":" + pad(secs, 2) + "," + pad(millis, 3);
    }

    function createUI(thisObj) {
        var win = (thisObj instanceof Panel) 
            ? thisObj 
            : new Window("palette", SCRIPT_NAME, undefined, { resizeable: true });

        win.orientation = "column";
        win.alignChildren = ["fill", "top"];
        win.spacing = 8;
        win.margins = 10;

        // Default compact width (fits kinetic chunks without excess black space)
        win.preferredSize.width = 420;
        if (win instanceof Window) {
            win.size = [420, 520];
        }

        // ----------------------------------------------------
        // SECTION 1: EXPORT WORK AREA
        // ----------------------------------------------------
        var pnlExport = win.add("panel", undefined, "1. Export Work Area");
        pnlExport.orientation = "column";
        pnlExport.alignChildren = ["fill", "top"];
        pnlExport.spacing = 6;
        pnlExport.margins = 8;

        var grpMode = pnlExport.add("group");
        grpMode.orientation = "row";
        grpMode.alignChildren = ["left", "center"];
        grpMode.spacing = 6;
        var lblMode = grpMode.add("statictext", undefined, "Mode:");
        lblMode.preferredSize.width = 50;

        var modeDropdown = grpMode.add("dropdownlist", undefined, [
            "Long (3–5 words)",
            "Short (2–3 words)",
            "Single Word (1 word)"
        ]);
        modeDropdown.selection = 0; // Default: Long
        modeDropdown.alignment = ["fill", "center"];

        var btnExport = pnlExport.add("button", undefined, "Generate Captions from Work Area");
        btnExport.preferredSize.height = 30;

        // ----------------------------------------------------
        // REVIEW SUBTITLES - FIXED IN-PLACE GRID
        // ----------------------------------------------------
        var pnlPreview = win.add("panel", undefined, "Review Subtitles");
        pnlPreview.orientation = "column";
        pnlPreview.alignChildren = ["fill", "top"];
        pnlPreview.spacing = 4;
        pnlPreview.margins = 8;

        // Table Header
        var grpHeader = pnlPreview.add("group");
        grpHeader.orientation = "row";
        grpHeader.alignChildren = ["left", "center"];
        grpHeader.spacing = 3;

        var hNum = grpHeader.add("statictext", undefined, "#");
        hNum.preferredSize.width = 34;

        var hTime = grpHeader.add("statictext", undefined, "Time (s)");
        hTime.preferredSize.width = 104;

        var hText = grpHeader.add("statictext", undefined, "Caption Text");
        hText.preferredSize.width = 220;
        hText.alignment = ["fill", "center"];

        var lblPageInfo = grpHeader.add("statictext", undefined, "0 / 0");
        lblPageInfo.preferredSize.width = 68;
        lblPageInfo.justify = "right";

        // Table Body with Scroll Column
        var grpTableArea = pnlPreview.add("group");
        grpTableArea.orientation = "row";
        grpTableArea.alignChildren = ["fill", "top"];
        grpTableArea.alignment = ["fill", "top"];
        grpTableArea.spacing = 3;

        var grpRows = grpTableArea.add("group");
        grpRows.orientation = "column";
        grpRows.alignChildren = ["fill", "top"];
        grpRows.alignment = ["fill", "top"];
        grpRows.spacing = 3;

        // Dedicated Scroll Column (▲ button, vertical scrollbar, ▼ button)
        var grpScrollCol = grpTableArea.add("group");
        grpScrollCol.orientation = "column";
        grpScrollCol.alignChildren = ["center", "fill"];
        grpScrollCol.alignment = ["right", "fill"];
        grpScrollCol.spacing = 2;
        grpScrollCol.preferredSize.width = 22;

        var btnScrollUp = grpScrollCol.add("button", undefined, "▲");
        btnScrollUp.preferredSize = [22, 20];

        var vScrollbar = grpScrollCol.add("scrollbar", undefined, 0, 0, 10);
        vScrollbar.preferredSize.width = 16;
        vScrollbar.preferredSize.height = 140;
        vScrollbar.alignment = ["center", "fill"];

        var btnScrollDown = grpScrollCol.add("button", undefined, "▼");
        btnScrollDown.preferredSize = [22, 20];

        var VISIBLE_ROWS = 7;
        var rowWidgets = [];

        for (var r = 0; r < VISIBLE_ROWS; r++) {
            var rowBox = grpRows.add("group");
            rowBox.orientation = "row";
            rowBox.alignChildren = ["left", "center"];
            rowBox.alignment = ["fill", "center"];
            rowBox.spacing = 3;
            rowBox.preferredSize.height = 24;

            // Number label
            var lblNum = rowBox.add("statictext", undefined, "#1");
            lblNum.preferredSize.width = 34;

            // Time group: Start [ 0.00 ] - End [ 0.00 ]
            var grpTime = rowBox.add("group");
            grpTime.orientation = "row";
            grpTime.alignChildren = ["left", "center"];
            grpTime.spacing = 2;
            grpTime.preferredSize.width = 104;

            var editStart = grpTime.add("edittext", undefined, "0.00");
            editStart.preferredSize = [46, 22];

            var lblDash = grpTime.add("statictext", undefined, "-");
            lblDash.preferredSize.width = 6;

            var editEnd = grpTime.add("edittext", undefined, "0.00");
            editEnd.preferredSize = [46, 22];

            // Subtitle text input (Native AE styling, stay in place)
            var editText = rowBox.add("edittext", undefined, "");
            editText.preferredSize = [220, 22];
            editText.alignment = ["fill", "center"];

            rowWidgets.push({
                rowBox: rowBox,
                lblNum: lblNum,
                grpTime: grpTime,
                editStart: editStart,
                lblDash: lblDash,
                editEnd: editEnd,
                editText: editText,
                rowIndex: r
            });
        }

        // Action buttons under grid
        var grpTableActions = pnlPreview.add("group");
        grpTableActions.orientation = "row";
        grpTableActions.alignChildren = ["fill", "center"];
        grpTableActions.spacing = 6;

        var btnAddRow = grpTableActions.add("button", undefined, "Add Row");
        btnAddRow.preferredSize.height = 24;

        var btnDeleteRow = grpTableActions.add("button", undefined, "Delete Row");
        btnDeleteRow.preferredSize.height = 24;

        var btnRefresh = grpTableActions.add("button", undefined, "Refresh");
        btnRefresh.preferredSize.height = 24;

        // ----------------------------------------------------
        // SECTION 2: IMPORT TO TIMELINE
        // ----------------------------------------------------
        var pnlImport = win.add("panel", undefined, "2. Import to Timeline");
        pnlImport.orientation = "column";
        pnlImport.alignChildren = ["fill", "top"];
        pnlImport.spacing = 6;
        pnlImport.margins = 8;

        var grpLang = pnlImport.add("group");
        grpLang.orientation = "row";
        grpLang.alignChildren = ["left", "center"];
        grpLang.spacing = 6;
        var lblLang = grpLang.add("statictext", undefined, "Language:");
        lblLang.preferredSize.width = 60;

        var langDropdown = grpLang.add("dropdownlist", undefined, [
            "Original Language",
            "Translate to Indonesian",
            "Translate to English"
        ]);
        langDropdown.selection = 0; // Default: Original
        langDropdown.alignment = ["fill", "center"];

        var btnImport = pnlImport.add("button", undefined, "Import to Timeline");
        btnImport.preferredSize.height = 32;

        // ----------------------------------------------------
        // STATUS BAR
        // ----------------------------------------------------
        var grpStatus = win.add("group");
        grpStatus.orientation = "row";
        grpStatus.alignChildren = ["left", "center"];
        var lblStatus = grpStatus.add("statictext", undefined, "Status: Ready");
        lblStatus.alignment = ["fill", "center"];

        function setStatus(msg) {
            lblStatus.text = "Status: " + msg;
            if (win.layout) {
                win.layout.layout(true);
            }
        }

        // ----------------------------------------------------
        // IN-PLACE GRID STATE & UNDO/REDO HISTORY
        // ----------------------------------------------------
        var selectedRowIndex = -1; // Indeks baris terpilih pada loadedCaptions (0..N-1)
        var scrollOffset = 0;      // 0 .. max(0, loadedCaptions.length - VISIBLE_ROWS)
        var isRendering = false;   // Menghindari rekursi event saat renderGrid

        var undoStack = [];
        var redoStack = [];
        var MAX_HISTORY = 40;

        function cloneCaptions(arr) {
            var out = [];
            for (var i = 0; i < arr.length; i++) {
                var it = arr[i];
                out.push({
                    index: it.index || (i + 1),
                    start: parseFloat(it.start) || 0.0,
                    end: parseFloat(it.end) || 0.0,
                    text: String(it.text || ""),
                    word_count: it.word_count || (it.text ? it.text.split(/\s+/).length : 0)
                });
            }
            return out;
        }

        function recordHistory() {
            undoStack.push(cloneCaptions(loadedCaptions));
            if (undoStack.length > MAX_HISTORY) {
                undoStack.shift();
            }
            redoStack = []; // Reset redo stack saat ada aksi baru
        }

        function performUndo() {
            if (undoStack.length === 0) {
                setStatus("Nothing to undo.");
                return;
            }
            commitAllEdits();
            redoStack.push(cloneCaptions(loadedCaptions));
            loadedCaptions = undoStack.pop();
            saveMasterCaptionsToDisk();
            renderGrid();
            setStatus("Undo successful.");
        }

        function performRedo() {
            if (redoStack.length === 0) {
                setStatus("Nothing to redo.");
                return;
            }
            commitAllEdits();
            undoStack.push(cloneCaptions(loadedCaptions));
            loadedCaptions = redoStack.pop();
            saveMasterCaptionsToDisk();
            renderGrid();
            setStatus("Redo successful.");
        }

        function commitCurrentEdit() {
            commitAllEdits();
        }

        function commitAllEdits() {
            if (isRendering) return;
            var changed = false;
            for (var r = 0; r < VISIBLE_ROWS; r++) {
                var capIdx = scrollOffset + r;
                if (capIdx >= 0 && capIdx < loadedCaptions.length) {
                    var w = rowWidgets[r];
                    var newTxt = w.editText.text.replace(/^\s+|\s+$/g, "");
                    var newStart = parseFloat(w.editStart.text);
                    var newEnd = parseFloat(w.editEnd.text);

                    if (newTxt !== loadedCaptions[capIdx].text) {
                        loadedCaptions[capIdx].text = newTxt;
                        loadedCaptions[capIdx].word_count = newTxt ? newTxt.split(/\s+/).length : 0;
                        changed = true;
                    }
                    if (!isNaN(newStart) && Math.abs(newStart - loadedCaptions[capIdx].start) > 0.001) {
                        loadedCaptions[capIdx].start = newStart;
                        changed = true;
                    }
                    if (!isNaN(newEnd) && Math.abs(newEnd - loadedCaptions[capIdx].end) > 0.001) {
                        loadedCaptions[capIdx].end = newEnd;
                        changed = true;
                    }
                }
            }
            if (changed) {
                recordHistory();
                saveMasterCaptionsToDisk();
            }
        }

        function updateSelectionIndicator() {
            for (var r = 0; r < VISIBLE_ROWS; r++) {
                var capIdx = scrollOffset + r;
                var w = rowWidgets[r];
                if (capIdx < loadedCaptions.length) {
                    w.lblNum.text = "#" + (capIdx + 1);
                } else {
                    w.lblNum.text = "";
                }
            }
        }

        // ----------------------------------------------------
        // HELPER: SCROLL & NAVIGATION
        // ----------------------------------------------------
        function scrollGridBy(delta) {
            commitAllEdits();
            var maxScroll = Math.max(0, loadedCaptions.length - VISIBLE_ROWS);
            var newOffset = scrollOffset + delta;
            if (newOffset > maxScroll) newOffset = maxScroll;
            if (newOffset < 0) newOffset = 0;
            if (newOffset !== scrollOffset) {
                scrollOffset = newOffset;
                renderGrid();
            }
        }

        // ----------------------------------------------------
        // RENDER VIRTUALIZED IN-PLACE GRID
        // ----------------------------------------------------
        function renderGrid(targetIndex) {
            isRendering = true;

            // Auto-scroll hanya dilakukan jika targetIndex diberikan secara eksplisit
            if (typeof targetIndex === "number") {
                if (targetIndex >= 0 && targetIndex < loadedCaptions.length) {
                    selectedRowIndex = targetIndex;
                } else if (targetIndex >= loadedCaptions.length) {
                    selectedRowIndex = loadedCaptions.length - 1;
                } else {
                    selectedRowIndex = -1;
                }

                if (selectedRowIndex >= 0) {
                    if (selectedRowIndex < scrollOffset) {
                        scrollOffset = selectedRowIndex;
                    } else if (selectedRowIndex >= scrollOffset + VISIBLE_ROWS) {
                        scrollOffset = selectedRowIndex - VISIBLE_ROWS + 1;
                    }
                }
            }

            if (loadedCaptions.length === 0) {
                selectedRowIndex = -1;
            } else if (selectedRowIndex >= loadedCaptions.length) {
                selectedRowIndex = loadedCaptions.length - 1;
            }

            var maxScroll = Math.max(0, loadedCaptions.length - VISIBLE_ROWS);
            if (scrollOffset > maxScroll) scrollOffset = maxScroll;
            if (scrollOffset < 0) scrollOffset = 0;

            vScrollbar.maxvalue = (maxScroll > 0) ? maxScroll : 1;
            vScrollbar.minvalue = 0;
            if (Math.round(vScrollbar.value) !== scrollOffset) {
                vScrollbar.value = scrollOffset;
            }
            vScrollbar.enabled = (maxScroll > 0);
            btnScrollUp.enabled = (scrollOffset > 0);
            btnScrollDown.enabled = (scrollOffset < maxScroll);

            // Update info posisi baris (misal: "1-7 / 24")
            if (loadedCaptions.length > 0) {
                var startNum = scrollOffset + 1;
                var endNum = Math.min(scrollOffset + VISIBLE_ROWS, loadedCaptions.length);
                lblPageInfo.text = startNum + "-" + endNum + " / " + loadedCaptions.length;
            } else {
                lblPageInfo.text = "0 / 0";
            }

            for (var r = 0; r < VISIBLE_ROWS; r++) {
                var w = rowWidgets[r];
                var capIdx = scrollOffset + r;

                if (capIdx < loadedCaptions.length) {
                    var c = loadedCaptions[capIdx];
                    c.index = capIdx + 1;
                    var isSelected = (selectedRowIndex === capIdx);

                    w.rowBox.visible = true;

                    // Nomor urut stabil tanpa panah
                    w.lblNum.text = "#" + c.index;

                    // Waktu Start & End (format detik 2 desimal)
                    w.editStart.text = formatTime(c.start);
                    w.editEnd.text = formatTime(c.end);

                    // Teks subtitle (Langsung di kotak input normal)
                    w.editText.text = String(c.text || "");

                    w.editStart.enabled = true;
                    w.editEnd.enabled = true;
                    w.editText.enabled = true;
                } else {
                    if (loadedCaptions.length === 0 && r === 0) {
                        w.rowBox.visible = true;
                        w.lblNum.text = "#1";
                        w.editStart.text = "0.00";
                        w.editEnd.text = "0.00";
                        w.editText.text = "(No subtitles yet. Click 'Add Row')";
                        w.editStart.enabled = false;
                        w.editEnd.enabled = false;
                        w.editText.enabled = false;
                    } else {
                        w.rowBox.visible = false;
                    }
                }
            }

            isRendering = false;

            if (win.layout) {
                win.layout.layout(true);
            }
        }

        // Attach event listener ke setiap baris tabel
        for (var idx = 0; idx < VISIBLE_ROWS; idx++) {
            (function(r) {
                var w = rowWidgets[r];

                // Klik nomor baris untuk memilih baris
                w.lblNum.addEventListener("mousedown", function() {
                    var capIdx = scrollOffset + r;
                    if (capIdx < loadedCaptions.length) {
                        selectedRowIndex = capIdx;
                        updateSelectionIndicator();
                        setStatus("Subtitle #" + (capIdx + 1) + " selected.");
                    }
                });

                // Klik atau fokus pada Start, End, atau Teks otomatis menandai baris terpilih
                w.editStart.addEventListener("mousedown", function() {
                    var capIdx = scrollOffset + r;
                    if (capIdx < loadedCaptions.length) {
                        selectedRowIndex = capIdx;
                        updateSelectionIndicator();
                    }
                });

                w.editEnd.addEventListener("mousedown", function() {
                    var capIdx = scrollOffset + r;
                    if (capIdx < loadedCaptions.length) {
                        selectedRowIndex = capIdx;
                        updateSelectionIndicator();
                    }
                });

                w.editText.addEventListener("mousedown", function() {
                    var capIdx = scrollOffset + r;
                    if (capIdx < loadedCaptions.length) {
                        selectedRowIndex = capIdx;
                        updateSelectionIndicator();
                    }
                });

                // Text editing events
                w.editText.onChanging = function() {
                    if (isRendering) return;
                    var capIdx = scrollOffset + r;
                    if (capIdx < loadedCaptions.length) {
                        loadedCaptions[capIdx].text = w.editText.text;
                    }
                };

                w.editText.onChange = function() {
                    if (isRendering) return;
                    var capIdx = scrollOffset + r;
                    if (capIdx < loadedCaptions.length) {
                        recordHistory();
                        var newTxt = w.editText.text.replace(/^\s+|\s+$/g, "");
                        loadedCaptions[capIdx].text = newTxt;
                        loadedCaptions[capIdx].word_count = newTxt ? newTxt.split(/\s+/).length : 0;
                        saveMasterCaptionsToDisk();
                        setStatus("Caption #" + (capIdx + 1) + " text saved.");
                    }
                };

                // Keyboard navigation dalam kolom teks (Enter, Panah Atas/Bawah, PageUp/PageDown)
                w.editText.addEventListener("keydown", function(k) {
                    if (k.keyName === "Enter" || k.keyCode === 13) {
                        w.editText.notify("onChange");
                        if (r + 1 < VISIBLE_ROWS && (scrollOffset + r + 1) < loadedCaptions.length) {
                            rowWidgets[r + 1].editText.active = true;
                            selectedRowIndex = scrollOffset + r + 1;
                            updateSelectionIndicator();
                        } else if ((scrollOffset + r + 1) < loadedCaptions.length) {
                            scrollGridBy(1);
                            rowWidgets[r].editText.active = true;
                        }
                        k.preventDefault();
                    } else if (k.keyName === "Down" || k.keyCode === 40) {
                        if (r === VISIBLE_ROWS - 1) {
                            scrollGridBy(1);
                            rowWidgets[r].editText.active = true;
                            k.preventDefault();
                        } else if (r + 1 < VISIBLE_ROWS && (scrollOffset + r + 1) < loadedCaptions.length) {
                            rowWidgets[r + 1].editText.active = true;
                            selectedRowIndex = scrollOffset + r + 1;
                            updateSelectionIndicator();
                            k.preventDefault();
                        }
                    } else if (k.keyName === "Up" || k.keyCode === 38) {
                        if (r === 0) {
                            scrollGridBy(-1);
                            rowWidgets[0].editText.active = true;
                            k.preventDefault();
                        } else if (r - 1 >= 0) {
                            rowWidgets[r - 1].editText.active = true;
                            selectedRowIndex = scrollOffset + r - 1;
                            updateSelectionIndicator();
                            k.preventDefault();
                        }
                    } else if (k.keyName === "PageDown" || k.keyCode === 34) {
                        scrollGridBy(VISIBLE_ROWS);
                        k.preventDefault();
                    } else if (k.keyName === "PageUp" || k.keyCode === 33) {
                        scrollGridBy(-VISIBLE_ROWS);
                        k.preventDefault();
                    }
                });

                // Start time editing events
                w.editStart.onChange = function() {
                    if (isRendering) return;
                    var capIdx = scrollOffset + r;
                    if (capIdx < loadedCaptions.length) {
                        var newStart = parseFloat(w.editStart.text);
                        if (!isNaN(newStart)) {
                            recordHistory();
                            loadedCaptions[capIdx].start = newStart;
                            saveMasterCaptionsToDisk();
                            setStatus("Caption #" + (capIdx + 1) + " start time updated.");
                        } else {
                            w.editStart.text = formatTime(loadedCaptions[capIdx].start);
                        }
                    }
                };

                // End time editing events
                w.editEnd.onChange = function() {
                    if (isRendering) return;
                    var capIdx = scrollOffset + r;
                    if (capIdx < loadedCaptions.length) {
                        var newEnd = parseFloat(w.editEnd.text);
                        if (!isNaN(newEnd)) {
                            recordHistory();
                            loadedCaptions[capIdx].end = newEnd;
                            saveMasterCaptionsToDisk();
                            setStatus("Caption #" + (capIdx + 1) + " end time updated.");
                        } else {
                            w.editEnd.text = formatTime(loadedCaptions[capIdx].end);
                        }
                    }
                };
            })(idx);
        }

        // Scroll controls: Tombol ▲ (Up) & ▼ (Down)
        btnScrollUp.onClick = function() {
            scrollGridBy(-1);
        };

        btnScrollDown.onClick = function() {
            scrollGridBy(1);
        };

        // Scrollbar events dengan guard anti-rekursi
        var isScrolling = false;
        vScrollbar.onChanging = function() {
            if (isRendering || isScrolling) return;
            isScrolling = true;
            try {
                commitAllEdits();
                var newOffset = Math.round(vScrollbar.value);
                var maxScroll = Math.max(0, loadedCaptions.length - VISIBLE_ROWS);
                if (newOffset > maxScroll) newOffset = maxScroll;
                if (newOffset < 0) newOffset = 0;
                scrollOffset = newOffset;
                renderGrid();
            } catch(e) {}
            isScrolling = false;
        };

        vScrollbar.onChange = function() {
            if (isRendering || isScrolling) return;
            isScrolling = true;
            try {
                commitAllEdits();
                var newOffset = Math.round(vScrollbar.value);
                var maxScroll = Math.max(0, loadedCaptions.length - VISIBLE_ROWS);
                if (newOffset > maxScroll) newOffset = maxScroll;
                if (newOffset < 0) newOffset = 0;
                scrollOffset = newOffset;
                renderGrid();
            } catch(e) {}
            isScrolling = false;
        };

        // Window-level Keyboard Shortcuts: PageUp/PageDown, Cmd/Ctrl+Z (Undo), Cmd/Ctrl+Shift+Z atau Ctrl+Y (Redo)
        win.addEventListener("keydown", function(ev) {
            if (ev.keyName === "PageDown" || ev.keyCode === 34) {
                scrollGridBy(VISIBLE_ROWS);
                ev.preventDefault();
                return;
            }
            if (ev.keyName === "PageUp" || ev.keyCode === 33) {
                scrollGridBy(-VISIBLE_ROWS);
                ev.preventDefault();
                return;
            }

            var isCmdOrCtrl = ev.metaKey || ev.ctrlKey;
            if (!isCmdOrCtrl) return;

            var key = (ev.keyName || "").toLowerCase();
            var code = ev.keyCode;

            // Undo: Cmd+Z atau Ctrl+Z (tanpa shift)
            if ((key === "z" || code === 90) && !ev.shiftKey) {
                performUndo();
                ev.preventDefault();
            }
            // Redo: Cmd+Shift+Z, Ctrl+Shift+Z, atau Ctrl+Y
            else if (((key === "z" || code === 90) && ev.shiftKey) || (key === "y" || code === 89)) {
                performRedo();
                ev.preventDefault();
            }
        });

        // ----------------------------------------------------
        // HELPER: LOAD & DISPLAY MASTER CAPTIONS
        // ----------------------------------------------------
        function loadCaptions() {
            var scriptFolder = getScriptFolder();
            var jsonFile = new File(scriptFolder + "/output/captions_master.json");
            if (!jsonFile.exists) {
                jsonFile = new File(scriptFolder + "/output/captions.json");
            }

            if (!jsonFile.exists) {
                loadedCaptions = [];
                undoStack = [];
                redoStack = [];
                renderGrid(-1);
                return 0;
            }

            try {
                jsonFile.open("r");
                jsonFile.encoding = "UTF-8";
                var raw = jsonFile.read();
                jsonFile.close();

                var data = eval("(" + raw + ")");
                currentMode = data.mode || "Long";
                currentTimeOffset = data.time_offset || 0.0;
                loadedCaptions = data.captions || [];
                undoStack = [];
                redoStack = [];

                renderGrid(0);
                return loadedCaptions.length;
            } catch(e) {
                setStatus("Error membaca data captions.");
                return 0;
            }
        }

        function saveMasterCaptionsToDisk() {
            var scriptFolder = getScriptFolder();
            
            // Generate clean JSON string
            var jsonStr = '{\n  "mode": "' + currentMode + '",\n  "time_offset": ' + currentTimeOffset + ',\n  "total_captions": ' + loadedCaptions.length + ',\n  "captions": [\n';
            for (var i = 0; i < loadedCaptions.length; i++) {
                var c = loadedCaptions[i];
                var escapedText = String(c.text || "")
                    .replace(/\\/g, "\\\\")
                    .replace(/"/g, '\"')
                    .replace(/\r/g, "")
                    .replace(/\n/g, "\\n");
                jsonStr += '    {\n' +
                           '      "index": ' + (i + 1) + ',\n' +
                           '      "start": ' + c.start + ',\n' +
                           '      "end": ' + c.end + ',\n' +
                           '      "text": "' + escapedText + '",\n' +
                           '      "word_count": ' + (c.text ? c.text.split(/\s+/).length : 0) + '\n' +
                           '    }' + (i < loadedCaptions.length - 1 ? ',' : '') + '\n';
            }
            jsonStr += '  ]\n}';

            // 1. Save to captions_master.json (our primary master record)
            var fMaster = new File(scriptFolder + "/output/captions_master.json");
            fMaster.open("w");
            fMaster.encoding = "UTF-8";
            fMaster.write(jsonStr);
            fMaster.close();

            // 2. Also keep active captions.json in sync
            var fJson = new File(scriptFolder + "/output/captions.json");
            fJson.open("w");
            fJson.encoding = "UTF-8";
            fJson.write(jsonStr);
            fJson.close();

            // 3. Update master captions.srt
            var fSrt = new File(scriptFolder + "/output/captions.srt");
            fSrt.open("w");
            fSrt.encoding = "UTF-8";
            var srtStr = "";
            for (var j = 0; j < loadedCaptions.length; j++) {
                var cj = loadedCaptions[j];
                srtStr += (j + 1) + "\n";
                srtStr += formatSrtTime(cj.start) + " --> " + formatSrtTime(cj.end) + "\n";
                srtStr += cj.text + "\n\n";
            }
            fSrt.write(srtStr);
            fSrt.close();
        }

        // Add Row Button: Tambah Baris Baru
        btnAddRow.onClick = function() {
            commitAllEdits();
            recordHistory();

            var insertIdx = 0;
            var prevEndTime = 0.0;

            if (loadedCaptions.length > 0) {
                if (selectedRowIndex >= 0 && selectedRowIndex < loadedCaptions.length) {
                    insertIdx = selectedRowIndex + 1;
                    prevEndTime = parseFloat(loadedCaptions[selectedRowIndex].end) || 0.0;
                } else {
                    insertIdx = loadedCaptions.length;
                    prevEndTime = parseFloat(loadedCaptions[loadedCaptions.length - 1].end) || 0.0;
                }
            }

            var newGroup = {
                index: insertIdx + 1,
                start: prevEndTime,
                end: prevEndTime + 2.0,
                text: "",
                word_count: 0
            };

            loadedCaptions.splice(insertIdx, 0, newGroup);

            // Re-index all captions 1..N
            for (var i = 0; i < loadedCaptions.length; i++) {
                loadedCaptions[i].index = i + 1;
            }

            saveMasterCaptionsToDisk();

            selectedRowIndex = insertIdx;
            renderGrid();

            // Fokuskan kursor ke baris baru tersebut
            var visibleR = insertIdx - scrollOffset;
            if (visibleR >= 0 && visibleR < VISIBLE_ROWS) {
                rowWidgets[visibleR].editText.active = true;
            }

            setStatus("Row #" + (insertIdx + 1) + " added.");
        };

        // Delete Row Button: Hapus Baris Terpilih
        btnDeleteRow.onClick = function() {
            if (selectedRowIndex < 0 || selectedRowIndex >= loadedCaptions.length || loadedCaptions.length === 0) {
                alert("Please select a subtitle row to delete first.", "Select Row");
                return;
            }

            commitAllEdits();
            recordHistory();

            var deletedNum = selectedRowIndex + 1;
            loadedCaptions.splice(selectedRowIndex, 1);

            // Re-index all captions 1..N
            for (var i = 0; i < loadedCaptions.length; i++) {
                loadedCaptions[i].index = i + 1;
            }

            saveMasterCaptionsToDisk();

            if (selectedRowIndex >= loadedCaptions.length) {
                selectedRowIndex = loadedCaptions.length - 1;
            }

            renderGrid();
            setStatus("Row #" + deletedNum + " deleted.");
        };

        // Refresh Button
        btnRefresh.onClick = function() {
            commitAllEdits();
            var cnt = loadCaptions();
            setStatus(cnt + " master captions reloaded.");
        };

        // ----------------------------------------------------
        // HANDLER: 1. EXPORT WORK AREA
        // ----------------------------------------------------
        btnExport.onClick = function() {
            commitCurrentEdit();
            if (!app.project) {
                alert("Please open an After Effects project first.", "No Project");
                return;
            }
            var comp = app.project.activeItem;
            if (!comp || !(comp instanceof CompItem)) {
                alert("Please select or open an active composition timeline in After Effects.", "Select Composition");
                return;
            }

            var workStart = comp.workAreaStart;
            var workDuration = comp.workAreaDuration;
            if (workDuration <= 0) {
                alert("Work Area duration is 0 seconds. Please set In (B) and Out (N) points on the timeline.", "Empty Work Area");
                return;
            }

            // Timeline placement offset for captions:
            // In After Effects, all layer inPoint/outPoint are relative to comp start (0.0s).
            // workStart (In Point marked by B) is the exact timeline offset.
            var timelineOffset = workStart;

            setStatus("Rendering Work Area audio...");

            // 1. Render Work Area Audio via RenderQueue
            var ext = ".aif";
            var rq = app.project.renderQueue;
            var item = rq.items.add(comp);

            // Apply native 'Current Settings' template:
            // Natively renders the active Work Area (In/Out points) regardless of comp start timecode
            // without manual timeSpan overrides that trigger blank frame warnings.
            try {
                item.applyTemplate("Current Settings");
            } catch(e) {}

            var om = item.outputModule(1);
            var applied = false;
            for (var i = 0; i < om.templates.length; i++) {
                var t = om.templates[i];
                if (t.indexOf("AIFF") !== -1) {
                    om.applyTemplate(t);
                    ext = ".aif";
                    applied = true;
                    break;
                } else if (t.indexOf("WAV") !== -1) {
                    om.applyTemplate(t);
                    ext = ".wav";
                    applied = true;
                    break;
                } else if (t.indexOf("Audio") !== -1) {
                    om.applyTemplate(t);
                    ext = (t.indexOf("WAV") !== -1) ? ".wav" : ".aif";
                    applied = true;
                    break;
                }
            }
            if (!applied) {
                om.applyTemplate(om.templates[0]);
                ext = ($.os.indexOf("Windows") !== -1) ? ".wav" : ".aif";
            }

            // Use unique timestamp to prevent collision with stale/cached audio files
            var renderNonce = new Date().getTime();
            var audioFile = new File(Folder.temp.fsName + "/ae_workarea_audio_" + renderNonce + ext);
            if (audioFile.exists) {
                try { audioFile.remove(); } catch(e) {}
            }
            om.file = audioFile;

            app.beginSuppressDialogs();
            try {
                rq.render();
            } catch(err) {
                app.endSuppressDialogs(false);
                item.remove();
                setStatus("Audio render failed.");
                alert("Failed to render audio:\n" + err.toString(), "Render Error");
                return;
            }
            app.endSuppressDialogs(false);
            item.remove();

            if (!audioFile.exists || audioFile.length <= 0) {
                setStatus("Failed to generate audio file.");
                alert("Work Area audio file could not be generated.", "Audio Error");
                return;
            }

            // 2. Call Python to Transcribe and Group
            setStatus("Transcribing speech & grouping phrases...");
            var modeStr = "long";
            if (modeDropdown.selection.index === 1) modeStr = "short";
            if (modeDropdown.selection.index === 2) modeStr = "single";

            var scriptFolder = getScriptFolder();
            var mainPyFile = new File(scriptFolder + "/main.py");
            if (!mainPyFile.exists) {
                alert("Core engine 'main.py' not found at:\n" + scriptFolder + "\n\nPlease select the 'core' folder to connect it.", "Connect Core Engine");
                var picked = Folder.selectDialog("Select 'core' folder for AI Text Generator");
                if (picked != null) {
                    var pFs = picked.fsName;
                    if (new File(pFs + "/main.py").exists) {
                        scriptFolder = pFs;
                    } else if (new File(pFs + "/core/main.py").exists) {
                        scriptFolder = pFs + "/core";
                    }
                    try {
                        app.settings.saveSetting("AITextGenerator", "CoreEnginePath", scriptFolder);
                    } catch(e) {}
                    mainPyFile = new File(scriptFolder + "/main.py");
                }
            }

            if (!mainPyFile.exists) {
                setStatus("Engine folder not connected.");
                alert("Cannot proceed because 'main.py' was not found.\nPlease ensure the 'core' folder exists on your computer.", "File Not Found");
                return;
            }

            var mainPy = mainPyFile.fsName;
            var pyCmd = getPythonBinary();
            var isWin = ($.os.indexOf("Windows") !== -1);
            var cmd = "";
            if (isWin) {
                cmd = 'cmd.exe /c chcp 65001 >nul && ' + pyCmd + ' "' + mainPy + '" --input "' + audioFile.fsName + '" --mode ' + modeStr + ' --time-offset ' + timelineOffset;
            } else {
                cmd = 'export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"; ' + pyCmd + ' "' + mainPy + '" --input "' + audioFile.fsName + '" --mode ' + modeStr + ' --time-offset ' + timelineOffset + ' 2>&1';
            }

            // Clear previous caption output files before generating fresh ones
            var masterFile = new File(scriptFolder + "/output/captions_master.json");
            if (masterFile.exists) { try { masterFile.remove(); } catch(e) {} }
            var activeFile = new File(scriptFolder + "/output/captions.json");
            if (activeFile.exists) { try { activeFile.remove(); } catch(e) {} }

            var pyOutput = "";
            try {
                pyOutput = system.callSystem(cmd);
            } catch(callErr) {
                setStatus("Script execution blocked by After Effects.");
                alert("After Effects blocked external script execution.\nEnable: Preferences > Scripting & Expressions > 'Allow Scripts to Write Files and Access Network'", "Permission Required");
                return;
            }

            // Clean up temporary audio file
            try {
                if (audioFile.exists) audioFile.remove();
            } catch(e) {}

            // Reload master captions into table ONLY if fresh masterFile was actually generated
            if (masterFile.exists || activeFile.exists) {
                var count = loadCaptions();
                if (count > 0) {
                    setStatus(count + " master captions ready.");
                    return;
                }
            }

            setStatus("Caption generation failed.");

            // Diagnosa penyebab kesalahan secara otomatis dan tampilkan ke editor
            var cleanOut = pyOutput ? pyOutput.replace(/^\s+|\s+$/g, "") : "";
            if (!cleanOut || cleanOut.indexOf("command not found") !== -1 || cleanOut.indexOf("not recognized") !== -1) {
                alert("Python 3 was not found on your system.\n\nPlease ensure Python 3 is installed.\nDetails: " + cleanOut, "Python Not Found");
            } else if (cleanOut.indexOf("Transcribed 0 words") !== -1 || cleanOut.indexOf("No spoken words") !== -1) {
                alert("No spoken words detected in the selected Work Area (B & N).\n\nTips:\n1. Ensure the Work Area spans audio where someone is speaking.\n2. Ensure the audio layer is not muted.\n3. Try expanding the Work Area.", "Silence / No Speech Detected");
            } else if (cleanOut.indexOf("Network connection failed") !== -1 || cleanOut.indexOf("nodename nor servname") !== -1 || cleanOut.indexOf("URLError") !== -1) {
                alert("Could not reach AI server (Network Connection Error).\n\nPlease check your internet connection.", "Network Error");
            } else if (cleanOut.indexOf("HTTP 401") !== -1 || cleanOut.indexOf("API Key is missing") !== -1) {
                alert("ElevenLabs API Key is missing or invalid in core/.env.\n\nDetails:\n" + cleanOut, "API Key Error");
            } else if (cleanOut.indexOf("HTTP 402") !== -1 || cleanOut.indexOf("quota") !== -1 || cleanOut.indexOf("credits") !== -1) {
                alert("ElevenLabs transcription credits/quota exhausted.", "Quota Exhausted");
            } else {
                alert("Failed to generate captions.\n\nOutput details:\n" + (cleanOut ? cleanOut : "(No output details)"), "Caption Error");
            }
        };

        // ----------------------------------------------------
        // HANDLER: 2. IMPORT KE TIMELINE
        // ----------------------------------------------------
        btnImport.onClick = function() {
            commitCurrentEdit();
            if (!app.project) {
                alert("Please open an After Effects project first.", "No Project");
                return;
            }
            var comp = app.project.activeItem;
            if (!comp || !(comp instanceof CompItem)) {
                alert("Please open a composition timeline in After Effects.", "Select Composition");
                return;
            }

            var scriptFolder = getScriptFolder();
            var masterFile = new File(scriptFolder + "/output/captions_master.json");
            if (!masterFile.exists) {
                masterFile = new File(scriptFolder + "/output/captions.json");
            }

            if (!masterFile.exists) {
                alert("No caption data available. Please generate captions from Work Area first.", "No Captions");
                return;
            }

            var langIdx = langDropdown.selection.index;
            var langCode = "original";
            if (langIdx === 1) langCode = "id";
            if (langIdx === 2) langCode = "en";

            var targetFileToLoad = masterFile;

            // If translation requested, translate chunk-by-chunk via Python (--translate-only, no deadlock!)
            if (langCode !== "original") {
                var langLabel = (langCode === "id") ? "Indonesian" : "English";
                setStatus("Translating to " + langLabel + " via AI...");

                // Remove stale language file from previous runs to ensure fresh translation
                var staleFile = new File(scriptFolder + "/output/captions_" + langCode + ".json");
                if (staleFile.exists) {
                    try { staleFile.remove(); } catch(e) {}
                }

                var mainPy = scriptFolder + "/main.py";
                var pyCmd = getPythonBinary();
                var isWin = ($.os.indexOf("Windows") !== -1);
                var cmd = "";
                if (isWin) {
                    cmd = 'cmd.exe /c chcp 65001 >nul && ' + pyCmd + ' "' + mainPy + '" --translate-only --lang ' + langCode + ' 2>&1';
                } else {
                    cmd = 'export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"; ' + pyCmd + ' "' + mainPy + '" --translate-only --lang ' + langCode + ' 2>&1';
                }
                var trOutput = "";
                try {
                    trOutput = system.callSystem(cmd);
                } catch(callErr) {
                    setStatus("Script execution blocked by After Effects.");
                    alert("After Effects blocked external script execution.\nEnable: Preferences > Scripting & Expressions > 'Allow Scripts to Write Files and Access Network'", "Permission Required");
                    return;
                }

                targetFileToLoad = new File(scriptFolder + "/output/captions_" + langCode + ".json");
                if (!targetFileToLoad.exists) {
                    setStatus("Translation failed.");
                    alert("AI Translation failed.\n\nDetails:\n" + trOutput, "Translation Failed");
                    return;
                }
                // CRUCIAL: Do NOT call loadCaptions() here!
                // The table in the panel stays showing the master transcript.
            } else {
                targetFileToLoad = masterFile;
            }

            setStatus("Creating text layers in timeline...");

            targetFileToLoad.open("r");
            targetFileToLoad.encoding = "UTF-8";
            var jsonText = targetFileToLoad.read();
            targetFileToLoad.close();

            var parsedData = null;
            try {
                parsedData = eval("(" + jsonText + ")");
            } catch(e) {
                setStatus("Failed to read subtitle data file.");
                alert("Failed to read subtitle data:\n" + e.toString(), "Parse Error");
                return;
            }

            var captions = parsedData.captions || [];
            if (captions.length === 0) {
                setStatus("No caption data found.");
                return;
            }

            // Validasi baris sebelum import (durasi 0 atau teks kosong)
            var invalidRows = [];
            for (var chk = 0; chk < captions.length; chk++) {
                var cRow = captions[chk];
                var sVal = parseFloat(cRow.start);
                var eVal = parseFloat(cRow.end);
                var tVal = (cRow.text || "").replace(/^\s+|\s+$/g, "");
                if (isNaN(sVal) || isNaN(eVal) || eVal <= sVal || tVal === "") {
                    invalidRows.push("#" + (chk + 1));
                }
            }
            if (invalidRows.length > 0) {
                var proceed = confirm(
                    "Warning: Row " + invalidRows.join(", ") + " has 0s duration or empty text and will be skipped.\n\nDo you want to continue?",
                    "Confirm Import"
                );
                if (!proceed) {
                    setStatus("Import cancelled.");
                    return;
                }
            }

            // Create Text Layers inside Undo Group
            var undoName = (langCode === "id") ? "Import Subtitles (Indonesian)" : (langCode === "en" ? "Import Subtitles (English)" : "Import Subtitles (Original)");
            app.beginUndoGroup(undoName);
            try {
                var compWidth = comp.width;
                var compHeight = comp.height;
                var posX = compWidth / 2;
                var posY = compHeight / 2;

                var langPrefix = (langCode === "id") ? "[ID] " : (langCode === "en" ? "[EN] " : "");

                // Handle layer duplicate naming
                var nameCounts = {};
                var names = [];
                for (var k = 0; k < captions.length; k++) {
                    var baseName = langPrefix + ((captions[k].text || "").replace(/^\s+|\s+$/g, "") || ("Caption_" + (k + 1)));
                    if (!nameCounts[baseName]) {
                        nameCounts[baseName] = 1;
                        names.push(baseName);
                    } else {
                        nameCounts[baseName]++;
                        names.push(baseName + " (" + nameCounts[baseName] + ")");
                    }
                }

                // Add layers backwards so #1 stays on top
                for (var i = captions.length - 1; i >= 0; i--) {
                    var c = captions[i];
                    var capText = c.text || "";
                    var sTime = parseFloat(c.start);
                    var eTime = parseFloat(c.end);

                    if (isNaN(sTime) || isNaN(eTime) || eTime <= sTime || capText.replace(/^\s+|\s+$/g, "") === "") {
                        continue;
                    }

                    var textLayer = comp.layers.addText(capText);
                    textLayer.name = names[i];
                    textLayer.startTime = 0;
                    textLayer.inPoint = sTime;
                    textLayer.outPoint = eTime;

                    var textProp = textLayer.property("Source Text");
                    if (textProp) {
                        var textDoc = textProp.value;
                        var isAllCaps = (textDoc.allCaps === true || (typeof FontCapsOption !== "undefined" && textDoc.fontCapsOption === FontCapsOption.FONT_ALL_CAPS));
                        if (isAllCaps) {
                            textDoc.text = capText.toUpperCase();
                        } else {
                            textDoc.text = capText;
                        }
                        if (typeof FontCapsOption !== "undefined" && FontCapsOption.FONT_NORMAL_CAPS) {
                            textDoc.fontCapsOption = FontCapsOption.FONT_NORMAL_CAPS;
                        }
                        textDoc.justification = ParagraphJustification.CENTER_JUSTIFY;
                        textProp.setValue(textDoc);
                    }

                    // Center anchor point to text bounding box
                    try {
                        var rect = textLayer.sourceRectAtTime(sTime + 0.01, false);
                        if (rect && rect.width > 0 && rect.height > 0) {
                            var ax = rect.left + rect.width / 2;
                            var ay = rect.top + rect.height / 2;
                            textLayer.property("Anchor Point").setValue([ax, ay]);
                        }
                    } catch(e) {}

                    textLayer.property("Position").setValue([posX, posY]);
                }

                app.endUndoGroup();

                var langTitle = (langCode === "id") ? "Indonesian" : (langCode === "en" ? "English" : "Original");
                setStatus(captions.length + " layers (" + langTitle + ") successfully created.");

                if (app.activeViewer) {
                    app.activeViewer.setActive();
                }
            } catch(layerErr) {
                app.endUndoGroup();
                setStatus("Error creating text layers.");
                alert("An error occurred while creating text layers:\n" + layerErr.toString(), "Layer Error");
            }
        };

        // Initial load of master captions into preview list
        loadCaptions();

        // Layout settings: layout children within container without shrinking the window
        win.layout.layout(true);
        win.onResizing = win.onResize = function() {
            this.layout.layout(true);
        };

        if (win instanceof Window) {
            win.size = [420, 520];
            win.layout.layout(true);
            win.center();
            win.show();
        }

        return win;
    }

    createUI(thisObj);
})(this);
