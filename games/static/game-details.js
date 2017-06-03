$(function() {
    $('#reply-1 textarea').focus(function() {
        $('#reply-2').hide();
        $('#reply-1 input').show();
        $('#reply-1 textarea').addClass('active');
    });
});