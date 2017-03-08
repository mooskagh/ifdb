(function($) {
    $.widget("crem.suggest", {
        options: {
            optToId: {},
            minLength: 1,
            id: -1,
        },

        _create: function() {
            var ops = this.options;
            ops.list = [];
            for (var key in ops.optToId) {
                if (ops.optToId.hasOwnProperty(key)) {
                    ops.list.push(key);
                    if (ops.optToId[key] == ops.id) {
                        this.element.val(key);
                    }
                }
            }
            this.element.autocomplete({
                source: ops.list,
                minLength: ops.minLength
            });
            if (ops.minValue == 0) {
                this.element.focus(function() {
                    $(this).autocomplete('search', $(this).val());
                });
            }
        }
    });


    $.widget("crem.authors", {
        options: {
            categoriesUrl: "/json/authors",
            value: [],
            roleToId: {},
            authorToId: {},
        },
        _create: function() {
            var self = this;
            $.getJSON(this.options.categoriesUrl, function(data) {
                $.extend(self.options, data);
                self._build();
            });
        },
        _build: function() {
            var self = this;
            var ops = self.options;

            for (var i = 0; i < ops.authors.length; ++i) {
                var a = ops.authors[i];
                ops.authorToId[a['name']] = a['id'];
            }

            for (var i = 0; i < ops.roles.length; ++i) {
                var a = ops.roles[i];
                ops.roleToId[a['title']] = a['id'];
            }

            var vals = this.options.value;
            for (var i = 0; i < vals.length; ++i) {
                var entry = $('<div class="entry"></div>');
                var role = $('<input class="narrow-list"/>')
                    .suggest({
                        optToId: ops.roleToId,
                        minLength: 0,
                        id: vals[i]['role']
                    });
                var author = $('<input class="wide-list"/>')
                    .suggest({
                        optToId: ops.authorToId,
                        minLength: 1,
                        id: vals[i]['author']
                    });
                var delicon = $('<span class="delicon">&#10006;</span>')
                role.appendTo(entry);
                author.appendTo(entry);
                delicon.appendTo(entry);
                entry.appendTo(this.element);
            }
        }
    });

})(jQuery);

function getCookie(name) {
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
        .val(getCookie('csrftoken'))
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