/**
 * @author narmiel
 *
 * Загрузка
 */

/**
 * @type {Quest}
 */
Game = null;

/**
 * @type {Player}
 */
GlobalPlayer = null;

/**
 * Files
 */
files = null;

quest = []; // todo

/**
 *
 */
var mode;

var URQW = (function() {
    function loadTextFromUrl(url) {
        $('#message').show();
        $.ajax({
            url: url,
            dataType: "text",
        }).done(function(msg) {
            console.log(msg);
            start(msg, url);
        }).fail(function () {
            loadFailed("Не удалось загрузить игру. Почему-то.");
        });
    }

    function loadZipFromUrl(url) {
        $('#message').show();
        JSZipUtils.getBinaryContent(url, function(err, data) {
            if (err) {
                loadFailed("Не удалось загрузить игру. Почему-то.");
            } else {
                loadZip(data, url);
            }
        });
    }

    function loadZip(data, name) {
        var zip = new JSZip(data);

        files = {};
        var qst = [];

        for (var key in zip.files) {
            if (!zip.files[key].dir) {
                var file = zip.file(key);
                if (file.name.split('.').pop().toLowerCase() == 'qst') {
                    if (file.name.substr(0, 1) == '_' || file.name.indexOf('/_') != -1) {
                        qst.unshift(file);
                    } else {
                        qst.push(file);
                    }
                } else if (file.name.split('.').pop().toLowerCase() == 'css') {
                    $('#additionalstyle').find('style').append(file.asBinary());
                } else if (file.name.split('.').pop().toLowerCase() == 'js') {
                    eval(win2unicode(file.asBinary())); // todo?
                } else {
                    files[file.name] = URL.createObjectURL(new Blob([(file.asArrayBuffer())], {type: MIME[file.name.split('.').pop()]}));
                }
            }
        }

        if (qst.length > 0) {
            quest = '';

            if (qst[0].name.lastIndexOf('/') != -1) {
                var dir = qst[0].name.substring(0, qst[0].name.lastIndexOf('/') + 1);

                for (var key in files) {
                    var newkey = key.substr(dir.length);
                    files[newkey] = files[key];
                    delete files[key];
                }
            }

            for (var i = 0; i < qst.length; i++) {
                quest = quest + '\r\n' + win2unicode(qst[i].asBinary());
            }

            start(quest, name);
        }
    }

    function loadFailed(text) {
        $('#message h3').text(text);
        $('#message').show();
    }

    /**
     * Запуск
     *
     * @param {String} msg тело квеста
     * @param {String} name имя игры или файла
     */
    function start(msg, name) {
        quest = null;
        window.onbeforeunload = function(e) {
            return 'confirm please';
        };

        $('#message').hide();
        $('#infopanel').hide();
        $('#logo').hide();

        Game = new Quest(msg);
        Game.name = name;

        Game.init();

        GlobalPlayer = new Player();

        if (mode) GlobalPlayer.setVar('urq_mode', mode);

        GlobalPlayer.Client.crtlInfo = $('#info');
        GlobalPlayer.Client.crtlInput = $('#input');
        GlobalPlayer.Client.crtlButtonField = $('#buttons');
        GlobalPlayer.Client.crtlTextField = $('#textfield');
        GlobalPlayer.Client.crtlInventory = $('#inventory');

        $('#game').show();

        GlobalPlayer.continue();
    }

    return {'loadZip': loadZipFromUrl,
            'loadText': loadTextFromUrl,
            'showError': loadFailed};
}());
