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
                minLength: ops.minLength
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
        }
    });


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

            for (var i = 0; i < vals.length; ++i) {
                var entry = $('<div class="entry"></div>');
                var role = $('<span class="narrow-list"/>')
                    .suggest({
                        optToId: ops.catToId,
                        minLength: 0,
                        id: vals[i][0],
                        showAll: true
                    });
                var author = $('<span class="wide-list"/>')
                    .suggest({
                        optToId: ops.valToId,
                        minLength: 1,
                        id: vals[i][1]
                    });
                var delicon = $('<span class="ico">&#10006;</span>')
                role.appendTo(entry);
                author.appendTo(entry);
                delicon.appendTo(entry);
                entry.appendTo(this.element);
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
