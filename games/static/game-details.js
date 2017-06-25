$(function() {
    "use strict";
    $('#reply-1 textarea').focus(function() {
        $('#reply-2').hide();
        $('#reply-1 input').show();
        $('#reply-1 textarea').addClass('active');
    });

    $('.comment-box .reply-link').click(function() {
        var reply = $('#reply-2');
        var target = $(this).closest('.comment-box');
        if (target != reply.closest('.comment-box')) {
            reply.find('[name="parent"]').val(target.attr('data-id'));
            reply.find('[name="subject"]')
                .val(target.find('.comment-subj').text());
            reply.find('textarea').val('');
            target.append(reply);
            reply.show();
        }

        $('#reply-1 input').hide();
        $('#reply-1 textarea').removeClass('active');
        reply.find('textarea').focus();
        return false;
    });

    $('.largeslider').slick({
        slidesToShow: 1,
        slidesToScroll: 1,
        centerMode: true,
        fade: true,
        asNavFor: '.smallslider'
    });

    $('.smallslider').slick({
        slidesToScroll: 1,
        dots: true,
        centerMode: true,
        focusOnSelect: true,
        variableWidth: true,
        infinite: false,
        asNavFor: '.largeslider'
    });
});