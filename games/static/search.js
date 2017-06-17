/*exported SEARCH*/
var SEARCH = (function() {
"use strict";

function BaseXVarintEncoder() {
    var dict = "0123456789abcdefghijklmnopqrstuvwxyz" +
               "ABCDEFGHIJKLMNOPQRSTUVWXYZ~-_.!*'(),$";
    var res = '';
    var headSpace = Math.floor(dict.length / 2);
    var trunkSpace = dict.length - headSpace;

    function addCodePoint(x) {
        res += dict[x];
    }

    this.value = function() {
        return res;
    };

    this.addInteger = function(x) {
        while(x >= headSpace) {
            x -= headSpace;
            addCodePoint(headSpace + x % trunkSpace);
            x = Math.floor(x / trunkSpace);
        }
        addCodePoint(x);
    };

    this.addString = function(x) {
        this.addInteger(x.length);
        for (var i = 0; i < x.length; ++i)
            this.addInteger(x.charCodeAt(i));
    };

    this.addSet = function(x) {
        var y = x;
        y.sort(function(a,b) {return a - b;});
        this.addInteger(y.length);
        for (var i = 0; i < y.length; ++i) {
          if (i === 0)
              this.addInteger(y[0]);
          else if (y[i] != y[i-1])
            this.addInteger(y[i] - y[i-1] - 1);
        }
    };

    this.addBools = function(x) {
        if (typeof(x) == 'boolean') x = [x];
        var val = 0;
        for (var i = 0; i < x.length; ++i)
            if (x[i]) val |= 1 << i;
        this.addInteger(val);
    };
    this.addBool = this.addBools;

    this.addHeader = function(typ, val) {
        this.addInteger(val * 16 + typ);
    };
}


function SrpFetcher() {
    var queryCache = {};

    function renderResults(data) {
        $('.gamelist-thumb-container').html(data).animate({opacity: 1}, 50);
    }

    this.loadResults = function(query){
        if (this.xhr) {
            this.xhr.abort();
            this.xhr = null;
        }
        if (queryCache.hasOwnProperty(query)) {
            renderResults(queryCache[query]);
        } else {
            $('.gamelist-thumb-container').animate({opacity: 0.5}, 50);
            this.xhr = $.ajax({
                url: '/json/search/',
                type: 'GET',
                data: {'q': query},
                cache: true,
                dataType: 'html',
            }).done(function(data) {
                queryCache[query] = data;
                renderResults(data);
            }).fail(function(xhr, textstatus) {
                if (textstatus != "abort") {
                    renderResults(
                      '<div class="gamelist-message">Ошибка какая-то.</div>');
                }
            });
        }
    };
}

function DecorateSearchItems() {
    var fetcher = new SrpFetcher();
    var timer = null;
    var gan = (typeof ga === 'function') ? ga : function(a, b, c ,d, e, f){
        // console.log(a, b, c, d, e, f);
    };

    function UpdateSearchList() {
        if (timer) {
            clearTimeout(timer);
            timer = null;
        }
        var enc = new BaseXVarintEncoder();
        $('tr[data-val]').trigger('encode-query', [enc]);
        gan('send', 'event', 'search', 'query', enc.value());
        window.history.pushState({'dirty': 'yes!'},
                                 null, '?q=' + enc.value());
        // TODO Analytics!
        fetcher.loadResults(enc.value());
    }

    function DeferUpdate() {
        if (timer) clearTimeout(timer);
        timer = setTimeout(UpdateSearchList, 500);
    }

    $(window).on('popstate', function(){
        window.location.href = window.location.href;
    });

    // Type 0: Sorting.
    $('tr[data-type="sorting"]').each(function(index, element) {
        $(element).find('[data-item-val]').click(function() {
            var el = $(this);
            var add = 0;
            if (el.hasClass('current')) {
                var dir = el.find('.sortbutton');
                if (dir.text().indexOf('▼') == -1)
                    dir.text('▼');
                else {
                    dir.text('▲');
                    add = 1;
                }
            } else {
                $(element).find('[data-item-val]').removeClass('current');
                $(element).find('.sortbutton').empty();
                el.addClass('current');
                el.find('.sortbutton').text('▼');
            }
            gan('send', 'event', 'search', 'sorting',
                2 * el.attr('data-item-val') + add);
            UpdateSearchList();
        });
    }).on('encode-query', function(event, enc){
        var parent = $(event.target);
        var el = parent.find('.current');
        var val = 2 * el.attr('data-item-val');
        if (el.find('.sortbutton').text().indexOf('▲') != -1)
            val += 1;

        if (val !== 0) {
            enc.addHeader(0, parent.attr('data-val'));
            enc.addInteger(val);
        }
    });

    // Type 1: Text.
    $('tr[data-type="text"]').each(function(index, element) {
        $(element).find('[data-item-val]').click(function() {
            gan('send', 'event', 'search', 'only_title',
                $(this).prop('checked') ? 'on' : 'off');
            if ($(element).find('input[type="text"]')[0].value !== '') {
                UpdateSearchList();
            }
        });
        $(element).find('input[type="text"]').on('input', DeferUpdate);
    }).on('encode-query', function(event, enc){
        var parent = $(event.target);
        var text = parent.find('input[type="text"]')[0].value;
        if (!text) return;
        enc.addHeader(1, 0);
        enc.addBool(parent.find('[data-item-val]')[0].checked);
        enc.addString(text);
    });

    // Type 2: Tags.
    $('tr[data-type="tags"]').each(function(index, element) {
        $(element).find('[data-item-val]').click(function() {
            $(this).toggleClass('current');
            gan('send', 'event', 'search', 'tag',
                $(this).hasClass('current') ? 'on' : 'off',
                parseInt($(this).attr('data-item-val')));
            UpdateSearchList();
        });
    }).on('encode-query', function(event, enc){
        var parent = $(event.target);
        var items = [];
        parent.find('.current').each(function() {
            items.push($(this).attr('data-item-val'));
        });
        if (items.length === 0) return;
        var category = parent.attr('data-val');
        enc.addHeader(2, category);
        enc.addSet(items);
    });

    // Advanced search button.
    $('.extended_search').click(function() {
        $(this).hide();
        $('tr[data-type]').show();
    });

    UpdateSearchList();
}

var res = {};
res.Decorate = DecorateSearchItems;
return res;
}());