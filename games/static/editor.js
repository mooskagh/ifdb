function GetCookie(name) {
  'use strict';
  var cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    var cookies = document.cookie.split(';');
    for (var i = 0; i < cookies.length; i++) {
      var cookie = jQuery.trim(cookies[i]);
      // Does this cookie string begin with the name we want?
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
    }
  return cookieValue;
}

(function($) {
  'use strict';

  function ReverseDict(d) {
    var res = {};
    for (var key in d) {
      if (d.hasOwnProperty(key)) {
        res[d[key]] = parseInt(key);
      }
      }
    return res;
  }

  $.widget('crem.suggest', {
    options: {
      optToId: {},
      minLength: 2,
      id: -1,
      showAll: false,
      allowNew: true,
      placeholder: '',
    },

    _create: function() {
      var ops = this.options;
      var input = null;
      var button = null;
      if (ops.showAll) {
        input = $('<input class="suggestinput-icon">')
                    .attr('placeholder', ops.placeholder)
                    .appendTo(this.element);
        button = $('<span class="ico">&#9660;</span>').appendTo(this.element);
      } else {
        input = $('<input class="suggestinput">')
                    .attr('placeholder', ops.placeholder)
                    .appendTo(this.element);
        }
      if (!ops.allowNew) {
        input.prop('readonly', true);
      }
      input.on('mousedown', function() {
        if (input.prop('readonly')) {
          if (!input.autocomplete('widget').is(':visible')) {
            input.autocomplete('search', '');
          } else {
            input.autocomplete('close');
          }
        }
      });
      ops.list = [];
      for (var key in ops.optToId) {
        if (ops.optToId.hasOwnProperty(key)) {
          ops.list.push(key);
          if (ops.optToId[key] == ops.id) {
            input.val(key);
          }
        }
      }
      input.autocomplete({
        source: ops.list,
        minLength: ops.minLength,
        select: function(event, ui) {
          input.trigger('creminput', ops.optToId[ui.item.value]);
        }
      });

      input.on('input', function() {
        input.trigger('creminput', ops.optToId[input.val()]);
      });
      input.on('creminput', function() {
        input.removeClass('invalidinput');
      });

      if (ops.showAll) {
        var wasOpen = false;
        button
            .on('mousedown',
                function() {
                  wasOpen = input.autocomplete('widget').is(':visible');
                })
            .click(function() {
              if (!wasOpen) input.autocomplete('search', '');
            });
        }
      if (ops.minLength === 0) {
        this.element.focus(function() {
          $(this).autocomplete('search', $(this).val());
        });
      }
      this.input = input;
    },

    empty: function() {
      return this.input.val() === '';
    },

    value: function() {
      var val = this.input.val();
      if (this.options.optToId.hasOwnProperty(val))
        return this.options.optToId[val];
      return val;
    },

    txtvalue: function(newVal) {
      if (newVal === undefined) {
        return this.input.val();
      } else {
        return this.input.val(newVal);
      }
    },

    optToId: function(newVal) {
      var ops = this.options;
      ops.optToId = newVal;
      ops.list = [];
      for (var key in ops.optToId) {
        if (ops.optToId.hasOwnProperty(key)) {
          ops.list.push(key);
        }
      }
      this.input.autocomplete('option', 'source', ops.list);
    },

    allowNew: function(newVal) {
      this.input.prop('readonly', !newVal);
      this.input.autocomplete('option', 'minLength', this.options.minLength);
    },

    isValid: function() {
      if (this.input.val() === '') {
        this.input.addClass('invalidinput');
        return false;
      } else {
        this.input.removeClass('invalidinput');
        return true;
      }
    }
  });

  function CreatePair(
      catToId, valToId, cat, val, allowAllCat, showAllVal, catsToValsToId,
      allowNewValCats, catPlaceholder, valPlaceholder) {
    var entry = $('<div class="entry"></div>');

    var cats = $('<span class="narrow-list"/>').suggest({
      minLength: 0,
      optToId: catToId,
      id: cat,
      showAll: true,
      allowNew: allowAllCat,
      placeholder: catPlaceholder,
    });

    var vals = $('<span class="wide-list"/>').suggest({
      minLength: catsToValsToId ? 0 : 2,
      optToId: catsToValsToId ? [] : valToId,
      id: val,
      showAll: showAllVal,
      placeholder: valPlaceholder,
    });

    var delicon = $('<span class="ico">&#10006;</span>');
    cats.appendTo(entry);
    vals.appendTo(entry);
    delicon.appendTo(entry);

    var obj = {
      element: entry,
      cats: cats,
      vals: vals,
      delicon: delicon
      // onempty  -- When loses focus and is empty
      // oninput - when first char appeared
      // ondel - when delete button is pressed.
    };

    obj.Destroy = function() {
      obj.element.remove();
    };

    function CheckEmpty() {
      if (cats.suggest('empty') && vals.suggest('empty') && obj.onempty)
        obj.onempty(obj);
    }
    cats.focusout(CheckEmpty);
    vals.focusout(CheckEmpty);

    function CheckInput() {
      if (obj.onchar) obj.onchar(obj);
    }
    cats.on('creminput', CheckInput);
    vals.on('creminput', CheckInput);

    function UpdateVals(event, catId) {
      if (catId === undefined) {
        vals.suggest('txtvalue', '');
        vals.suggest('optToId', {});
        vals.suggest('allowNew', false);
        return;
        }
      var valToId = catsToValsToId[catId];
      var v = vals.suggest('txtvalue');
      var allowNew = allowNewValCats.indexOf(catId) != -1;
      if (!allowNew && !valToId.hasOwnProperty(v)) {
        vals.suggest('txtvalue', '');
      }
      vals.suggest('option', 'minLength', allowNew ? 2 : 0)
      vals.suggest('allowNew', allowNew);
      vals.suggest('optToId', valToId);
      }

    if (catsToValsToId) {
      UpdateVals();
      cats.on('creminput', UpdateVals);
    }

    delicon.click(function() {
      if (obj.delicon) obj.ondel(obj);
    });

    obj.IsValid = function() {
      var a1 = cats.suggest('isValid');
      var a2 = vals.suggest('isValid');
      return a1 && a2;
    };

    return obj;
  }

  $.widget('crem.propSelector', {
    options: {
      idToCat: {},
      idToVal: {},
      catToVals: undefined,
      allowNewValCats: undefined,
      _catToId: {},
      _valToId: {},
      values: [],
      allowNewCat: true,
      showAllVals: false,
      catPlaceholder: '',
      valPlaceholder: '',
    },
    _create: function() {
      var self = this;
      var ops = self.options;
      var vals = ops.values;

      var objs = [];
      ops.objs = objs;

      if (ops.catToVals) {
        for (var key in ops.catToVals) {
          if (ops.catToVals.hasOwnProperty(key)) {
            var y = ops.catToVals[key];
            for (var x in y) {
              if (y.hasOwnProperty(x)) {
                ops.idToVal[y[x]] = x;
              }
            }
          }
        }
      }

      ops._catToId = ReverseDict(ops.idToCat);
      ops._valToId = ReverseDict(ops.idToVal);

      for (var i = 0; i < vals.length + 1; ++i) {
        var v = ['', ''];
        if (i < vals.length) {
          v = vals[i];
        }
        this.addEntry(v[0], v[1]);
      }
    },

    addEntry: function(cats, vals) {
      cats = cats || '';
      vals = vals || '';
      var self = this;
      var ops = this.options;
      var objs = ops.objs;

      function OnDel(obj) {
        for (var i = 0; i < objs.length - 1; ++i) {
          if (obj === objs[i]) {
            obj.Destroy();
            objs.splice(i, 1);
            return;
          }
        }
        }

      function OnInput(obj) {
        if (obj == objs[objs.length - 1]) {
          self.addEntry();
        }
        }

      if (objs.length > 0) objs[objs.length - 1].delicon.show();
      var el = CreatePair(
          ops._catToId, ops._valToId, cats, vals, ops.allowNewCat,
          ops.showAllVals, ops.catToVals, ops.allowNewValCats,
          ops.catPlaceholder, ops.valPlaceholder);
      el.delicon.hide();
      el.element.appendTo(self.element);
      objs.push(el);
      el.ondel = OnDel;
      el.onempty = OnDel;
      el.onchar = OnInput;
    },

    isValid: function() {
      var isValid = true;
      for (var i = 0; i < this.options.objs.length - 1; ++i) {
        isValid &= this.options.objs[i].IsValid();
        }
      return isValid;
    },

    values: function() {
      var res = [];
      for (var i = 0; i < this.options.objs.length - 1; ++i) {
        var o = this.options.objs[i];
        res.push([o.cats.suggest('value'), o.vals.suggest('value')]);
        }
      return res;
    },
    merge: function(d) {
      var o = this.options;
      for (var i = 0; i < d.length; ++i) {
        var cat = d[i][0];
        var val = d[i][1];
        if (typeof(cat) == 'number') cat = o.idToCat[cat];
        if (typeof(val) == 'number') val = o.idToVal[val];
        var alreadyExists = false;
        for (var j = 0; j < o.objs.length - 1; ++j) {
          var oo = o.objs[j];
          if (oo.cats.suggest('txtvalue') == cat &&
              oo.vals.suggest('txtvalue') == val) {
            alreadyExists = true;
            break;
          }
          }
        if (alreadyExists) continue;
        var obj = o.objs[o.objs.length - 1];
        this.addEntry();
        obj.cats.suggest('txtvalue', cat);
        obj.cats.trigger('creminput', o._catToId[cat]);
        obj.vals.suggest('txtvalue', val);
      }
    }
  });

  function CreateUrlEntry(categories, cat, url, desc) {
    var entry = $('<div class="entry"></div>');
    var catToId = {};
    var enabledCats = {};
    for (var i = 0; i < categories.length; ++i) {
      catToId[categories[i].title] = categories[i].id;
      if (categories[i].uploadable) {
        enabledCats[categories[i].id] = true;
      }
      }

    var cats = $('<span class="narrow-list"/>').suggest({
      minLength: 0,
      optToId: catToId,
      id: cat,
      showAll: true,
      allowNew: false,
      placeholder: 'Тип',
    });

    var desc_el = $('<input class="descinput" placeholder="Описание">');
    var url_el = $('<input class="urlinput" placeholder="URL">');
    var or_el = $('<span>или</span>');
    var button_el = $('<button id="upload_button">Закачать</button>');
    var file_el = $('<input type="file" style="display:none;">');
    var delicon = $('<span class="ico">&#10006;</span>');
    var progress = $('<progress></progress>').hide();
    desc_el.appendTo(entry);
    delicon.appendTo(entry);
    cats.appendTo(entry);
    url_el.appendTo(entry);
    or_el.appendTo(entry);
    button_el.appendTo(entry);
    file_el.appendTo(entry);
    progress.appendTo(entry);

    button_el.click(function() {
      file_el.click();
    });
    file_el.change(function() {
      if (file_el.val() === '') return;
      progress.show();
      var formData = new FormData();
      formData.append('csrfmiddlewaretoken', GetCookie('csrftoken'));
      formData.append('file', file_el[0].files[0]);
      var req = $.ajax({
        url: '/json/upload/',
        type: 'POST',
        data: formData,
        cache: false,
        contentType: false,
        processData: false,
        dataType: 'json',
        xhr: function() {
          var myXhr = $.ajaxSettings.xhr();
          if (myXhr.upload) {
            myXhr.upload.addEventListener('progress', function(e) {
              if (e.lengthComputable) {
                $('progress').attr({
                  value: e.loaded,
                  max: e.total,
                });
              }
            }, false);
            }
          return myXhr;
        },
      });
      req.done(function(json) {
        url_el.val(json.url);
      });
      req.fail(function(jqXHR, textStatus) {
        progress.hide();
        window.alert('Что-то не закачалось: ' + textStatus);
      });
    });

    var obj = {
      element: entry,
      delicon: delicon,
      cats: cats,
      url: url_el,
      desc: desc_el,
      button: button_el,
      // onempty  -- When loses focus and is empty
      // oninput - when first char appeared
      // ondel - when delete button is pressed.
    };

    obj.Destroy = function() {
      obj.element.remove();
    };

    function UpdateUploadButton(event, catId) {
      button_el.prop('disabled', !enabledCats.hasOwnProperty(catId));
    }

    cats.on('creminput', UpdateUploadButton);
    UpdateUploadButton();

    function CheckEmpty() {
      if (cats.suggest('empty') && url_el.val() === '' &&
          desc_el.val() === '' && obj.onempty)
        obj.onempty(obj);
    }

    cats.focusout(CheckEmpty);
    url_el.focusout(CheckEmpty);
    desc_el.focusout(CheckEmpty);

    function CheckInput() {
      if (obj.onchar) obj.onchar(obj);
    }
    cats.on('creminput', CheckInput);
    url_el.on('keydown', CheckInput);
    desc_el.on('keydown', CheckInput);
    url_el.on('input', function() {
      url_el.removeClass('invalidinput');
    });
    desc_el.on('input', function() {
      desc_el.removeClass('invalidinput');
    });

    delicon.click(function() {
      if (obj.delicon) obj.ondel(obj);
    });

    obj.IsValid = function() {
      var valid = cats.suggest('isValid');
      if (url_el.val() === '') {
        url_el.addClass('invalidinput');
        valid = false;
      } else {
        url_el.removeClass('invalidinput');
        }
      if (desc_el.val() === '') {
        desc_el.addClass('invalidinput');
        valid = false;
      } else {
        desc_el.removeClass('invalidinput');
        }
      return valid;
    };

    return obj;
  }

  $.widget('crem.urlUpload', {
    options: {
      categories: {},
      values: [],
    },
    _create: function() {
      var vals = this.options.values;

      var objs = [];
      this.options.objs = objs;

      for (var i = 0; i < vals.length + 1; ++i) {
        var cat = '';
        var url = '';
        var desc = '';
        if (i < vals.length) {
          cat = vals[i][0];
          url = vals[i][1];
          desc = vals[i][2];
        }
        this.AddEntry(cat, url, desc);
      }
    },
    AddEntry: function(cat, url, desc) {
      var self = this;
      cat = cat || '';
      url = url || '';
      desc = desc || '';
      var objs = this.options.objs;

      function OnDel(obj) {
        for (var i = 0; i < objs.length - 1; ++i) {
          if (obj === objs[i]) {
            obj.Destroy();
            objs.splice(i, 1);
            return;
          }
        }
        }

      function OnInput(obj) {
        if (obj == objs[objs.length - 1]) {
          self.AddEntry();
        }
        }

      if (objs.length > 0) objs[objs.length - 1].delicon.show();
      var el = CreateUrlEntry(this.options.categories, cat, url, desc);
      el.delicon.hide();
      el.element.appendTo(this.element);
      objs.push(el);
      el.ondel = OnDel;
      el.onempty = OnDel;
      el.onchar = OnInput;
    },
    isValid: function() {
      var isValid = true;
      for (var i = 0; i < this.options.objs.length - 1; ++i) {
        isValid &= this.options.objs[i].IsValid();
        }
      return isValid;
    },
    values: function() {
      var res = [];
      for (var i = 0; i < this.options.objs.length - 1; ++i) {
        var o = this.options.objs[i];
        res.push([o.cats.suggest('value'), o.desc.val(), o.url.val()]);
        }
      return res;
    },
    merge: function(d) {
      var o = this.options;

      var idToCat = {};
      var enabledCats = {};
      for (var i = 0; i < o.categories.length; ++i) {
        idToCat[o.categories[i].id] = o.categories[i].title;
        if (o.categories[i].uploadable) {
          enabledCats[o.categories[i].id] = true;
        }
        }

      var cloneEnabled = false;
      for (i = 0; i < d.length; ++i) {
        var cat = d[i][0];
        var desc = d[i][1];
        var url = d[i][2];
        if (typeof(cat) == 'number') {
          cloneEnabled = enabledCats.hasOwnProperty(cat);
          cat = idToCat[cat];
          }
        var alreadyExists = false;
        for (var j = 0; j < o.objs.length - 1; ++j) {
          var oo = o.objs[j];
          if (oo.url.val() == url && oo.cats.suggest('value') == cat) {
            alreadyExists = true;
            break;
          }
          }
        if (alreadyExists) continue;
        var obj = o.objs[o.objs.length - 1];
        this.AddEntry();
        obj.cats.suggest('txtvalue', cat);
        obj.url.val(url);
        obj.desc.val(desc);
        obj.button.prop('disabled', !cloneEnabled);
      }
    }
  });

})(jQuery);

/*exported EDITOR*/
var EDITOR = (function() {
  'use strict';

  function BuildAuthors(element, data) {
    var cats = {};
    var vals = {};
    var vs = [];

    data.roles.forEach(function(v) {
      cats[v.id] = v.title;
    });
    data.authors.forEach(function(v) {
      vals[v.id] = v.name;
    });
    data.value.forEach(function(v) {
      vs.push([v.role, v.author]);
    });

    element.propSelector({
      idToCat: cats,
      idToVal: vals,
      values: vs,
      catPlaceholder: 'Роль',
      valPlaceholder: 'Имя',
    });
    }

  function BuildTags(element, data) {
    var cats = {};
    var cats2vals = {};
    var openCats = [];
    var vs = [];

    for (var i = 0; i < data.categories.length; ++i) {
      var v = data.categories[i];
      cats[v.id] = v.name;
      var catVals = {};
      for (var j = 0; j < v.tags.length; ++j) {
        var w = v.tags[j];
        catVals[w.name] = w.id;
      }
      cats2vals[v.id] = catVals;
      if (v.allow_new_tags) {
        openCats.push(v.id);
      }
    }
    element.propSelector({
      idToCat: cats,
      catToVals: cats2vals,
      allowNewValCats: openCats,
      values: vs,
      showAllVals: true,
      allowNewCat: false,
      catPlaceholder: 'Категория',
      valPlaceholder: 'Свойство',
    });
    }

  function BuildLinks(element, data) {
    element.urlUpload({'categories': data.categories});
    }

  function InitEditor() {
    var params = {};
    var game_id = $('.gameedit').attr('game-id');
    if (game_id) params.game_id = game_id;

    $.getJSON('/json/gameinfo/', params, function(data) {
      BuildAuthors($('#authors'), data.authortypes);
      BuildTags($('#tags'), data.tagtypes);
      BuildLinks($('#links'), data.linktypes);

      if (data.hasOwnProperty('gamedata')) UpdateFields(data.gamedata);
    });
    }

  function PostRedirect(url, data) {
    var form = $('<form method="POST" style="display:none;" />');
    form.attr('action', url);
    var input = $('<input type="hidden" name="json"/>');
    input.val(JSON.stringify(data));
    input.appendTo(form);
    $('<input type="hidden" name="csrfmiddlewaretoken"/>')
        .val(GetCookie('csrftoken'))
        .appendTo(form);
    form.appendTo(document.body);
    form.submit();
    }

  function SubmitGameJson() {
    var res = {};
    res.title = $('#title').val();
    var isValid = true;
    if (res.title === '') {
      $('#title_warning').show();
      isValid = false;
    }
    isValid &= $('#authors').propSelector('isValid');
    isValid &= $('#tags').propSelector('isValid');
    isValid &= $('#links').urlUpload('isValid');
    if (!isValid) return;

    res.desc = $('#description').val();
    res.release_date = $('#release_date').val();
    res.authors = $('#authors').propSelector('values');
    res.tags = $('#tags').propSelector('values');
    res.links = $('#links').urlUpload('values');

    var game_id = $('.gameedit').attr('game-id');
    if (game_id) res.game_id = game_id;
    PostRedirect('/game/store/', res);
    }

  function UpdateFields(data) {
    if (data.hasOwnProperty('title')) {
      $('#title').val(data.title);
      }
    if (data.hasOwnProperty('desc')) {
      var oldVal = $('#description').val();
      if (oldVal) {
        data.desc += '\n\n---\n_предыдущая версия описания:_\n\n' + oldVal;
      }
      $('#description').val(data.desc);
      }
    if (data.hasOwnProperty('release_date')) {
      $('#release_date').val(data.release_date);
      }
    if (data.hasOwnProperty('authors')) {
      $('#authors').propSelector('merge', data.authors);
      }
    if (data.hasOwnProperty('tags')) {
      $('#tags').propSelector('merge', data.tags);
      }
    if (data.hasOwnProperty('links')) {
      $('#links').urlUpload('merge', data.links);
    }
    }

  function ImportGame() {
    var url = $('#import_url').val();
    if (!url) {
      $('#import_warning').show();
      $('#import_warning').text('А укажите URL');
      return;
    }
    $('#import_warning').hide();

    if (typeof ga === 'function') {
      ga('send', 'event', 'editor', 'import', url);
    }

    $.getJSON('/json/import/', {'url': url}, function(data) {
      if (data.hasOwnProperty('error')) {
        $('#import_warning').show();
        $('#import_warning').text(data.error);
        return;
      }
      UpdateFields(data);
      $('#import_url').val('');
    });
    }

  var res = {};
  res.Init = InitEditor;
  res.SubmitGameJson = SubmitGameJson;
  res.ImportGame = ImportGame;
  return res;
}());
