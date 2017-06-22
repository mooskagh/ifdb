from .models import TaskQueueElement
from django.db.models import Q
import datetime
import importlib
import json
import logging
import os
import signal
import time

# TODO Build more robust filename
PID_FILE = '/tmp/ifdbworker.pid'


def IsPosix():
    return os.name == 'posix'


def NotifyWorker():
    if IsPosix():
        try:
            with open(PID_FILE, 'r') as f:
                pid = int(f.read())
                os.kill(pid, signal.SIGUSR1)
        except:
            pass


def _EnqueueCreate(func, argv, name, onfail, priority, retries, retry_minutes,
                   dependency, kwarg):
    t = TaskQueueElement()
    t.name = name
    t.command_json = json.dumps({
        'module': func.__module__,
        'name': func.__name__,
        'argv': argv,
        'kwarg': kwarg,
    })
    if onfail:
        t.onfail = json.dumps({
            'module': onfail.__module__,
            'name': onfail.__name__
        })
    t.retries_left = retries
    t.retry_minutes = retry_minutes
    t.enqueue_time = datetime.datetime.now()
    t.dependency = dependency
    return t


def Enqueue(func,
            *argv,
            name=None,
            onfail=None,
            priority=100,
            retries=3,
            retry_minutes=2000,
            dependency=None,
            **kwarg):
    t = _EnqueueCreate(func, argv, name, onfail, priority, retries,
                       retry_minutes, dependency, kwarg)
    t.save()
    NotifyWorker()
    return t


def EnqueueOrGet(func, *argv, name=None, priority=100, **kwarg):
    try:
        t = TaskQueueElement.objects.get(name=name)
        if t.priority > priority:
            t.priority = priority
            t.save()
            NotifyWorker()
        return t
    except TaskQueueElement.DoesNotExists:
        return Enqueue(func, name=name, *argv, **kwarg)


def Worker():
    do_exit = False

    def handler(signal, frame):
        print('Exiting...')
        nonlocal do_exit
        do_exit = True

    if IsPosix():
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGINT, handler)

    while True:
        if do_exit:
            break
        t = (TaskQueueElement.objects.filter(pending=True)
             .filter(Q(dependency=None) | Q(dependency__success=True)).filter(
                 Q(scheduled_time=None) | Q(
                     scheduled_time__lte=datetime.datetime.now())).order_by(
                         'priority', 'enqueue_time'))
        logging.info('%d tasks waiting' % t.count())
        if t:
            t = t[0]
            t.pending = False
            t.start_time = datetime.datetime.now()
            t.save()
            call = json.loads(t.command_json)
            i = importlib.import_module(call['module'])
            func = getattr(i, call['name'])
            try:
                func(*call['argv'], **call['kwarg'])
                t.success = True
                t.finish_time = datetime.datetime.now()
                t.save()
            except Exception as e:
                logging.exception(e)
                if t.retries_left > 0:
                    t.pending = True
                    t.retries_left -= 1
                    t.scheduled_time = datetime.datetime.now(
                    ) + datetime.timedelta(minutes=t.retry_minutes)
                    t.save()
                else:
                    t.fail = True
                    t.save()
                    if t.onfail_json:
                        call = json.loads(t.onfail_json)
                        i = importlib.import_module(call['module'])
                        func = getattr(i, call['name'])
                        try:
                            func(t, call)
                        except Exception as e:
                            logging.exception(e)
            continue
        else:
            t = (TaskQueueElement.objects.filter(pending=True).filter(
                Q(dependency=None) | Q(dependency__success=True)).filter(
                    scheduled_time__isnull=False).order_by('scheduled_time')
                 )[:1]
            if t:
                t = t[0]
                delta = int((t.scheduled_time - datetime.datetime.now()
                             ).total_seconds()) + 1
                logging.info('All tasks pending, waiting for %d seconds' %
                             delta)
                if IsPosix():
                    signal.alert(delta)
            else:
                logging.info('Done everything!')

        if IsPosix():
            signal.pause()
        else:
            time.sleep(60)
