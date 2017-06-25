from django.db import models

class TaskQueueElement(models.Model):
    def __str__(self):
        def StatusStr():
            if self.fail:
                return 'fail'
            if self.pending:
                return 'pending'
            if self.success:
                return 'success'
            return 'none'

        return "%s -- %s (%s)" % (StatusStr(), self.name, self.command_json)

    name = models.CharField(
        db_index=True, max_length=255, null=True, blank=True)
    command_json = models.CharField(max_length=512)
    priority = models.IntegerField(default=100)
    # json:
    #   module: str
    #   function: str
    #   argv: []
    #   kwarg: {}
    onfail_json = models.CharField(null=True, blank=True, max_length=512)
    retries_left = models.IntegerField(default=3)
    retry_minutes = models.IntegerField(default=2000)
    cron = models.CharField(null=True, blank=True, max_length=32)
    enqueue_time = models.DateTimeField(null=True, blank=True)
    scheduled_time = models.DateTimeField(null=True, blank=True)
    start_time = models.DateTimeField(null=True, blank=True)
    finish_time = models.DateTimeField(null=True, blank=True)
    dependency = models.ForeignKey('self', null=True, blank=True)
    pending = models.BooleanField(default=True)
    success = models.BooleanField(default=False)
    fail = models.BooleanField(default=False)