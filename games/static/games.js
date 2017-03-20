(function($) {
    function ReverseDict(d) {
        var res = {};
        for (var key in d) {
            if (d.hasOwnProperty(key)) {
                res[d[key]] = key;
                }
            }
        return res;
    }

    $.widget("crem.suggest", {
        options: {
            optToId: {},
            minLength: 1,
            id: -1,
            showAll: false,
            allowNew: true
        },

        _create: function() {
            var ops = this.options;
            if (ops.showAll) {
                var input = $('<input class="suggestinput-icon">')
                    .appendTo(this.element);
                var button = $('<span class="ico">&#9660;</span>')
                    .appendTo(this.element);
            } else {
                var input = $('<input class="suggestinput">')
                    .appendTo(this.element);
            }
            if (!ops.allowNew) {
                input.prop("readonly", true).on('mousedown', function() {
                    if (!input.autocomplete("widget").is(":visible")) {
                        input.autocomplete('search', '');
                    } else {
                        input.autocomplete('close');
                    }
                });
            }
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
                select: function(event) {
                    input.trigger('creminput');
                }
            });

            input.on('input', function() {
                input.trigger('creminput');
            });
            input.on('creminput', function() {
                input.removeClass('invalidinput');
            });

            if (ops.showAll) {
                var wasOpen = false;
                button.on("mousedown", function() {
                    wasOpen = input.autocomplete("widget").is(":visible");
                })
                .click(function() {
                    if (!wasOpen)
                        input.autocomplete('search', '');
                });
            }
            if (ops.minLength == 0) {
                this.element.focus(function() {
                    $(this).autocomplete('search', $(this).val());
                });
            }
            this.input = input;
        },

        empty: function() {
            return this.input.val() == '';
        },

        value: function() {
            var val = this.input.val();
            if (val in this.options.optToId)
                return this.options.optToId[val];
            return val;
        },

        isValid: function() {
            if (this.input.val() == '') {
                this.input.addClass('invalidinput');
                return false;
            } else {
                this.input.removeClass('invalidinput');
                return true;
            }
        }
    });

    function CreatePair(catToId, valToId, cat, val, showAllVal, allowNewVal) {
        var entry = $('<div class="entry"></div>');

        var cats = $('<span class="narrow-list"/>')
            .suggest({
                minLength: 0,
                optToId: catToId,
                id: cat,
                showAll: true
            });

        var vals = $('<span class="wide-list"/>')
            .suggest({
                optToId: valToId,
                id: val,
                showAll: showAllVal
            });

        var delicon = $('<span class="ico">&#10006;</span>')
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
        }

        function CheckEmpty() {
            if (cats.suggest('empty') && vals.suggest('empty') && obj.onempty)
                obj.onempty(obj);
        }
        cats.focusout(CheckEmpty);
        vals.focusout(CheckEmpty);

        function CheckInput() {
            if (obj.onchar)
                obj.onchar(obj);
        }
        cats.on('creminput', CheckInput);
        vals.on('creminput', CheckInput);

        delicon.click(function() {
            if (obj.delicon) obj.ondel(obj);
        });

        obj.IsValid = function() {
            var a1 = cats.suggest('isValid');
            var a2 = vals.suggest('isValid');
            return a1 && a2;
        }

        return obj;
    }

    $.widget("crem.propSelector", {
        options: {
            idToCat: {},
            idToVal: {},
            catToVals: undefined,
            _catToId: {},
            _valToId: {},
            values: [],
            allowNewCat: true,
            showAllVals: false,
        },
        _create: function() {
            var self = this;
            var ops = self.options;
            var vals = ops.values;

            var objs = [];
            ops.objs = objs;

            ops._catToId = ReverseDict(ops.idToCat);
            ops._valToId = ReverseDict(ops.idToVal);

            function OnDel(obj) {
                for (var i = 0; i < objs.length-1; ++i) {
                    if (obj === objs[i]) {
                        obj.Destroy();
                        objs.splice(i, 1);
                        return;
                    }
                }
            }

            function OnInput(obj) {
                if (obj == objs[objs.length-1]) {
                    obj.delicon.show();
                    var el = CreatePair(ops._catToId, ops._valToId,
                                        '', '', ops.showAllVals);
                    el.delicon.hide();
                    el.element.appendTo(self.element);
                    objs.push(el);
                    el.ondel = OnDel;
                    el.onempty = OnDel;
                    el.onchar = OnInput;
                }
            }

            for (var i = 0; i < vals.length + 1; ++i) {
                var v = ['', ''];
                if (i < vals.length) {
                    v = vals[i];
                }
                var el = CreatePair(ops._catToId, ops._valToId,
                                    v[0], v[1], ops.showAllVals);
                if (i == vals.length) {
                    el.delicon.hide();
                }
                objs.push(el);

                el.ondel = OnDel;
                el.onempty = OnDel;
                el.onchar = OnInput;

                el.element.appendTo(this.element);
            }
        },

        isValid: function() {
            var isValid = true;
            for (var i = 0; i < this.options.objs.length-1; ++i) {
                isValid &= this.options.objs[i].IsValid();
            }
            return isValid;
        },

        values: function() {
            var res = [];
            for (var i = 0; i < this.options.objs.length-1; ++i) {
                var o = this.options.objs[i];
                res.push([o.cats.suggest('value'), o.vals.suggest('value')]);
            }
            return res;
        }
    });

})(jQuery);

function BuildAuthors(element) {
    $.getJSON('/json/authors/', function(data) {
        var cats = {};
        var vals = {};
        var vs = [];

        for (var i = 0; i < data['roles'].length; ++i) {
            var v = data['roles'][i];
            cats[v['id']] = v['title'];
        }
        for (var i = 0; i < data['authors'].length; ++i) {
            var v = data['authors'][i];
            vals[v['id']] = v['name'];
        }
        for (var i = 0; i < data['value'].length; ++i) {
            var v = data['value'][i];
            vs.push([v['role'], v['author']]);
        }

        element.propSelector({
            idToCat: cats,
            idToVal: vals,
            values: vs
        });
    });
}

function BuildTags(element) {
    $.getJSON('/json/tags/', function(data) {
        var cats = {};
        var vals = {};
        var cats2vals = {};
        var vs = [];

        for (var i = 0; i < data['categories'].length; ++i) {
            var v = data['categories'][i];
            cats[v['id']] = v['name'];
            var v = data['categories'][i];
            var catVals = [];
            for (var j = 0; j < v['tags'].length; ++j) {
                var w = v['tags'][j];
                catVals.push(w['id']);
                vals[w['id']] = w['name'];
            }
            cats2vals[v['id']] = catVals;
        }
        console.log(cats);
        console.log(vals);
        element.propSelector({
            idToCat: cats,
            idToVal: vals,
            catToVals: cats2vals,
            values: vs,
            showAllVals: true
        });
    });
}

function GetCookie(name) {
    var cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        var cookies = document.cookie.split(';');
        for (var i = 0; i < cookies.length; i++) {
            var cookie = jQuery.trim(cookies[i]);
            // Does this cookie string begin with the name we want?
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue =
                    decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
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
    res['title'] = $("#title").val();
    var isValid = true;
    if (res['title'] == '') {
        $("#title_warning").show();
        isValid = false;
    }
    isValid &= $('#authors').propSelector('isValid');
    if (!isValid) return;

    res['description'] = $('#description').val();
    res['release_date'] = $('#release_date').val();
    res['authors'] = $('#authors').propSelector('values');
    PostRedirect('/store_game/', res);
}
