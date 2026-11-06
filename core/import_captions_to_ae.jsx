/**
 * import_captions_to_ae.jsx
 * 
 * Adobe After Effects ExtendScript to import synchronized AI caption phrases.
 * 
 * Features:
 * - Validates active composition.
 * - Prompts to select generated captions.json file.
 * - Creates editable text layers for each caption phrase.
 * - Synchronizes inPoint and outPoint with speech timing.
 * - Positions captions at lower-center of the composition with readable styling.
 * - Wraps in an Undo Group ("Import AI Captions") for one-click undo (Cmd+Z / Ctrl+Z).
 */

(function importAICaptions() {
    // 1. Verify project and active composition
    if (!app.project) {
        alert("Please open a project with an active composition before running this script.", "No Project Open");
        return;
    }

    var comp = app.project.activeItem;
    if (!comp || !(comp instanceof CompItem)) {
        alert("No active composition detected!\n\nPlease select or open a composition timeline in After Effects and run this script again.", "Active Composition Required");
        return;
    }

    // 2. Prompt user to select captions.json file
    var defaultPath = (new File($.fileName)).parent.fsName + "/output/captions.json";
    var defaultFile = new File(defaultPath);
    var targetFile = null;

    if (defaultFile.exists) {
        targetFile = defaultFile;
    } else {
        targetFile = File.openDialog("Select Generated Captions JSON File", "JSON Files:*.json;All Files:*.*");
    }

    if (!targetFile) {
        // User cancelled dialog
        return;
    }

    if (!targetFile.exists) {
        alert("The selected file does not exist:\n" + targetFile.fsName, "File Not Found");
        return;
    }

    // 3. Read and parse JSON
    targetFile.open("r");
    targetFile.encoding = "UTF-8";
    var jsonText = targetFile.read();
    targetFile.close();

    var captionsData = null;
    try {
        if (typeof JSON !== "undefined" && JSON.parse) {
            captionsData = JSON.parse(jsonText);
        } else {
            // Safe fallback for older ExtendScript engines without native JSON
            captionsData = eval("(" + jsonText + ")");
        }
    } catch (e) {
        alert("Failed to parse JSON file:\n" + e.toString(), "JSON Parse Error");
        return;
    }

    // Validate that we have an array of captions
    var captions = null;
    var modeName = "";
    if (captionsData instanceof Array) {
        captions = captionsData;
    } else if (captionsData && captionsData.captions instanceof Array) {
        captions = captionsData.captions;
        if (captionsData.mode) {
            modeName = captionsData.mode;
        }
    } else {
        alert("Invalid JSON format. Expected an array of caption items.", "Format Error");
        return;
    }

    if (captions.length === 0) {
        alert("The captions file contains 0 caption groups.", "Empty Captions");
        return;
    }

    // Helper: zero pad index (e.g., 1 -> "001")
    function padZero(num, size) {
        var s = "000000000" + num;
        return s.substr(s.length - size);
    }

    // 4. Create text layers inside an Undo Group
    app.beginUndoGroup("Import AI Captions");

    try {
        var createdLayers = [];
        var compWidth = comp.width;
        var compHeight = comp.height;
        var posX = compWidth / 2;
        var posY = compHeight / 2; // EXACT dead-center of the composition

        // Pre-compute layer names matching caption text, appending (2), (3) etc. for duplicates
        var nameOccurrences = {};
        var layerNames = [];
        for (var k = 0; k < captions.length; k++) {
            var rawText = captions[k].text ? captions[k].text.toString() : "";
            var trimmedText = rawText.replace(/^\s+|\s+$/g, "");
            if (!trimmedText) {
                trimmedText = "Caption_" + (k + 1);
            }

            if (!nameOccurrences[trimmedText]) {
                nameOccurrences[trimmedText] = 1;
                layerNames.push(trimmedText);
            } else {
                nameOccurrences[trimmedText]++;
                layerNames.push(trimmedText + " (" + nameOccurrences[trimmedText] + ")");
            }
        }

        // Iterate backwards so Caption_001 ends up on top of the layer stack
        for (var i = captions.length - 1; i >= 0; i--) {
            var item = captions[i];
            var captionText = item.text || "";
            var startTime = parseFloat(item.start);
            var endTime = parseFloat(item.end);

            if (isNaN(startTime) || isNaN(endTime) || endTime <= startTime) {
                continue;
            }

            // Create editable text layer (inherits user's last-used font, size, & color from AE Character panel)
            var textLayer = comp.layers.addText(captionText);
            textLayer.name = layerNames[i];

            // Timeline synchronization
            textLayer.startTime = 0; // Anchor timeline to 0s
            textLayer.inPoint = startTime;
            textLayer.outPoint = endTime;

            // Apply text settings: center align paragraph & preserve AE Character preferences
            var textProp = textLayer.property("Source Text");
            if (textProp) {
                var textDoc = textProp.value;

                // Check if user's AE Character panel has All Caps (TT) enabled
                var isAllCapsActive = (textDoc.allCaps === true || (typeof FontCapsOption !== "undefined" && textDoc.fontCapsOption === FontCapsOption.FONT_ALL_CAPS));

                if (isAllCapsActive) {
                    // If user's AE default is All Caps, convert text to TRUE uppercase (e.g. 'WHAT', 'FLORIDA', 'LIKE?')
                    // This prevents font glyph glitches where 'h' and 'l' fail to capitalize.
                    textDoc.text = captionText.toUpperCase();
                } else {
                    // Otherwise keep exact ElevenLabs casing (e.g. 'What', 'Florida', 'like?')
                    textDoc.text = captionText;
                }

                // Render in normal caps mode so clean, genuine glyphs are displayed
                if (typeof FontCapsOption !== "undefined" && FontCapsOption.FONT_NORMAL_CAPS) {
                    textDoc.fontCapsOption = FontCapsOption.FONT_NORMAL_CAPS;
                }

                textDoc.justification = ParagraphJustification.CENTER_JUSTIFY;
                // Note: fontSize, font, and styling are left untouched to respect AE's active Character defaults!
                textProp.setValue(textDoc);
            }

            // 3. Exact Dead-Center Alignment (adjust Anchor Point to text bounding box center)
            try {
                var evalTime = startTime + 0.01;
                var rect = textLayer.sourceRectAtTime(evalTime, false);
                if (rect && rect.width > 0 && rect.height > 0) {
                    var anchorX = rect.left + rect.width / 2;
                    var anchorY = rect.top + rect.height / 2;
                    textLayer.property("Anchor Point").setValue([anchorX, anchorY]);
                }
            } catch (e) {
                // Keep default anchor if sourceRectAtTime is unsupported
            }

            // Set Position to exact composition center
            var posProp = textLayer.property("Position");
            if (posProp) {
                posProp.setValue([posX, posY]);
            }

            // Assign distinct color label in timeline (Label 11 is Orange, 9 is Cyan)
            textLayer.label = 11;

            createdLayers.push(textLayer);
        }

        app.endUndoGroup();

        var modeInfo = modeName ? " [Mode: " + modeName + "]" : "";
        alert("Successfully imported " + createdLayers.length + " caption layers" + modeInfo + " into composition:\n\"" + comp.name + "\"\n\nPress Cmd+Z (Mac) or Ctrl+Z (Windows) if you need to undo.", "Captions Imported");

    } catch (err) {
        app.endUndoGroup();
        alert("An error occurred while creating layers:\n" + err.toString(), "Import Error");
    }
})();
