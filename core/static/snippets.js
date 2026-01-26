$(function() {
  $('.card--async').each(function(i, e) {
    $.ajax({
        url: '/json/snippet/',
        type: 'GET',
        data: {
            's': $(e).attr('card--snippet-id'),
        },
        cache: false,
        dataType: 'html',
    }).done(function(data) {
      $(e).replaceWith(data);
      $('.grid-container').masonry('layout');
    }).fail(function(xhr, textstatus) {
      $(e).closest('.grid-box').remove();
      $('.grid-container').masonry('layout');
    });
  });
});