(function($) {
    $.widget("crem.suggest", {
        options: {
            optToId: {},
            minLength: 1,
            id: -1,
            showAll: false
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
                select: function() {
                    input.trigger('input');
                }
            });

            if (ops.showAll) {
                var wasOpen = false;
                button .on( "mousedown", function() {
                    wasOpen = input.autocomplete( "widget" ).is( ":visible" );
                })
                .click(function() {
                    if (!wasOpen)
                        input.autocomplete('search', '');
                });
            }
            if (ops.minValue == 0) {
                this.element.focus(function() {
                    $(this).autocomplete('search', $(this).val());
                });
            }
            this.input = input;
        },

        empty: function() {
            return this.input.val() == '';
        }
    });

    function CreatePair(catToId, valToId, cat, val) {
        var entry = $('<div class="entry"></div>');

        var cats = $('<span class="narrow-list"/>')
            .suggest({
                optToId: catToId,
                minLength: 0,
                id: cat,
                showAll: true
            });

        var vals = $('<span class="wide-list"/>')
            .suggest({
                optToId: valToId,
                minLength: 1,
                id: val
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
        cats.on('input', CheckInput);
        vals.on('input', CheckInput);

        delicon.click(function() {
            if (obj.delicon) obj.ondel(obj);
        });

        return obj;
    }

    $.widget("crem.propSelector", {
        options: {
            catToId: {},
            valToId: {},
            values: [],
            allowNewCat: true,
        },
        _create: function() {
            var self = this;
            var ops = self.options;
            var vals = ops.values;

            var objs = [];

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
                    var el = CreatePair(ops.catToId, ops.valToId, '', '');
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
                var el = CreatePair(ops.catToId, ops.valToId, v[0], v[1]);
                if (i == vals.length) {
                    el.delicon.hide();
                }
                objs.push(el);

                el.ondel = OnDel;
                el.onempty = OnDel;
                el.onchar = OnInput;

                el.element.appendTo(this.element);
            }
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
            cats[v['title']] = v['id'];
        }
        for (var i = 0; i < data['authors'].length; ++i) {
            var v = data['authors'][i];
            vals[v['name']] = v['id'];
        }
        for (var i = 0; i < data['value'].length; ++i) {
            var v = data['value'][i];
            vs.push([v['role'], v['author']]);
        }

        element.propSelector({
            catToId: cats,
            valToId: vals,
            values: vs
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
    if (res['title'] == '') {
        $("#title_warning").show();
        return;
    }
    res['description'] = $('#description').val();
    res['release_date'] = $('#release_date').val();
    PostRedirect('/store_game/', res);
}
