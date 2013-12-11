# -*- coding: UTF-8
#
#   notification_sched
#   ******************
#
# Notification implementation, documented along the others asynchronous
# operations, in Architecture and in jobs/README.md

import sys

from twisted.internet.defer import inlineCallbacks

from globaleaks.rest import errors
from globaleaks.jobs.base import GLJob
from globaleaks.plugins.base import Event
from globaleaks import models
from globaleaks.settings import transact, transact_ro, GLSetting
from globaleaks.utils.utility import log, pretty_date_time
from globaleaks.plugins import notification
from globaleaks.handlers import admin, rtip
from globaleaks.models import Receiver

def serialize_receivertip(rtip):
    rtip_dict = {
        'id': unicode(rtip.id),
        'creation_date' : unicode(pretty_date_time(rtip.creation_date)),
        'last_access' : unicode(pretty_date_time(rtip.last_access)),
        'expressed_pertinence' : unicode(rtip.expressed_pertinence),
        'access_counter' : int(rtip.access_counter),
    }
    return rtip_dict

def serialize_internalfile(ifile):
    rfile_dict = {
        'name': unicode(ifile.name),
        'sha2sum': unicode(ifile.sha2sum),
        'content_type': unicode(ifile.content_type),
        'size': unicode(ifile.size),
        'creation_date' : unicode(pretty_date_time(ifile.creation_date)),
    }
    return rfile_dict

# Note: is used tip.serialize_comment until more information are not
# requested in Comment notification template (like some Tip info)


class APSNotification(GLJob):
    notification_settings = None

    @transact_ro
    def _get_notification_settings(self, store):
        """
        notification setting need to contains bot template
        and systemsettings
        """
        from globaleaks.handlers.admin import admin_serialize_notification

        notif = store.find(models.Notification).one()

        if not notif.server:
            return None

        return admin_serialize_notification(notif, GLSetting.memory_copy.default_language)


    @transact
    def create_tip_notification_events(self, store):
        """
        This transaction will return all a list of tuples containing the tips
        for which the notification event has not been run.

        Returns:

            events: a list of tuples containing (tip_id, an instance of
                :class:`globaleaks.plugins.base.Event`).

        """
        events = []

        # settings.notification_plugins contain a list of supported plugin
        # at the moment only 1. so [0] is used. but different context/receiver
        # may use different code-plugin:
        cplugin = GLSetting.notification_plugins[0]

        plugin = getattr(notification, cplugin)()

        not_notified_tips = store.find(models.ReceiverTip,
            models.ReceiverTip.mark == models.ReceiverTip._marker[0]
        )

        node_desc = admin.admin_serialize_node(store.find(models.Node).one(),
            GLSetting.memory_copy.default_language)

        if not_notified_tips.count():
            log.debug("Receiver Tips found to be notified: %d" % not_notified_tips.count() )

        for rtip in not_notified_tips:

            if not rtip.internaltip or not rtip.internaltip.context:
                log.err("(tip_notification) Integrity failure: missing InternalTip|Context")
                continue

            context_desc = admin.admin_serialize_context(rtip.internaltip.context, GLSetting.memory_copy.default_language)

            receiver_desc = admin.admin_serialize_receiver(rtip.receiver, GLSetting.memory_copy.default_language)
            if not receiver_desc.has_key('mail_address'):
                log.err("Receiver %s lack of email address!" % rtip.receiver.name)
                continue

            # check if the receiver has the Tip notification enabled or not
            if not receiver_desc['tip_notification']:
                log.debug("Receiver %s has tip notification disabled" % rtip.receiver.user.username)
                rtip.mark = models.ReceiverTip._marker[3] # 'disabled'
                store.commit()
                continue

            tip_desc = serialize_receivertip(rtip)

            event = Event(type=u'tip', trigger='Tip',
                            notification_settings=self.notification_settings,
                            trigger_info=tip_desc,
                            node_info=node_desc,
                            receiver_info=receiver_desc,
                            context_info=context_desc,
                            plugin=plugin)
            events.append((unicode(rtip.id), event))

        return events

    @transact
    def tip_notification_succeeded(self, store, result, tip_id):
        """
        This is called when the tip notification has succeeded
        """
        rtip = store.find(models.ReceiverTip, models.ReceiverTip.id == tip_id).one()

        if not rtip:
            raise errors.TipGusNotFound

        log.debug("Email: +[Success] Notification Tip receiver %s" % rtip.receiver.user.username)
        rtip.mark = models.ReceiverTip._marker[1] # 'notified'

    @transact
    def tip_notification_failed(self, store, failure, tip_id):
        """
        This is called when the tip notification has failed.
        """
        rtip = store.find(models.ReceiverTip, models.ReceiverTip.id == tip_id).one()

        if not rtip:
            raise errors.TipGusNotFound

        log.debug("Email: -[Fail] Notification Tip receiver %s" % rtip.receiver.user.username)
        rtip.mark = models.ReceiverTip._marker[2] # 'unable to notify'

    @inlineCallbacks
    def do_tip_notification(self, tip_events):
        for tip_id, event in tip_events:

            notify = event.plugin.do_notify(event)
            notify.addCallback(self.tip_notification_succeeded, tip_id)
            notify.addErrback(self.tip_notification_failed, tip_id)

            # we need to wait on single mail send basis to not be prone to DoS
            # and be forced to open so many outgoing connections.
            yield notify

    @transact
    def create_message_notification_events(self, store):
        """
        Creates events for performing notification of newly added messages.

        Returns:
            events: a list of tuples containing ((message_id, receiver_id), an instance of
                :class:`globaleaks.plugins.base.Event`).


        """
        events = []
        cplugin = GLSetting.notification_plugins[0]

        plugin = getattr(notification, cplugin)()

        not_notified_messages = store.find(models.Message,
                                           models.Message.mark == models.Message._marker[0]
        )

        node_desc = admin.admin_serialize_node(store.find(models.Node).one(), GLSetting.memory_copy.default_language)

        if not_notified_messages.count():
            log.debug("Messages found to be notified: %d" % not_notified_messages.count() )

        for message in not_notified_messages:

            if message.receivertip is None:
                log.err("Message %s has ReceiverTip broken reference" % message.id)
                message.mark = models.Message._marker[2] # 'unable to notify'
                continue

            receiver = store.find(Receiver, Receiver.id == message.receivertip.receiver_id).one()
            if not receiver:
                log.err("Message %s do not find receiver!?" % message.id)

            if not receiver.mail_address:
                log.err("Receiver %s lack of email address!" % receiver.name)
                continue

            receiver_desc = admin.admin_serialize_receiver(receiver, GLSetting.memory_copy.default_language)
            log.debug("Messages receiver: %d" % message.internaltip.receivers.count())

            context = message.receivertip.internaltip.context
            if not context:
                log.err("Reference chain fail!")
                continue

            context_desc = admin.admin_serialize_context(context, GLSetting.memory_copy.default_language)


            message_desc = rtip.receiver_serialize_message(message)
            message.mark = models.Message._marker[1] # 'notified'

            if message._types == u"receiver":
                log.debug("Receiver is the Author (%s): skipped" % receiver.user.username)
                continue

            # check if the receiver has the Message notification enabled or not
            if not receiver.message_notification:
                log.debug("Receiver %s has message notification disabled: skipped [source: %s]" % (
                    receiver.user.username, message.author))
                continue

            event = Event(type=u'message', trigger='Message',
                          notification_settings=self.notification_settings,
                          trigger_info=message_desc,
                          node_info=node_desc,
                          receiver_info=receiver_desc,
                          context_info=context_desc,
                          plugin=plugin)

            events.append(((unicode(message.id), unicode(receiver.id)), event))

        return events

    @transact_ro
    def message_notification_succeeded(self, store, result, message_id, receiver_id):
        """
        This is called when the message notification has succeeded
        """
        receiver = store.find(models.Receiver, models.Receiver.id == receiver_id).one()

        if not receiver:
            raise errors.ReceiverGusNotFound

        log.debug("Email: +[Success] Notification of message receiver %s" % receiver.user.username)

    @transact_ro
    def message_notification_failed(self, store, failure, message_id, receiver_id):
        """
        This is called when the message notification has failed.
        """
        receiver = store.find(models.Receiver, models.Receiver.id == receiver_id).one()

        if not receiver:
            raise errors.ReceiverGusNotFound

        log.debug("Email: -[Fail] Notification of message receiver %s" % receiver.user.username)

    @inlineCallbacks
    def do_message_notification(self, message_events):
        for message_receiver_id, event in message_events:
            message_id, receiver_id = message_receiver_id

            notify = event.plugin.do_notify(event)
            notify.addCallback(self.message_notification_succeeded, message_id, receiver_id)
            notify.addErrback(self.message_notification_failed, message_id, receiver_id)

            # we need to wait on single mail send basis to not be prone to DoS
            # and be forced to open so many outgoing connections.
            yield notify

    @transact
    def create_comment_notification_events(self, store):
        """
        Creates events for performing notification of newly added comments.

        Returns:
            events: a list of tuples containing ((comment_id, receiver_id), an instance of
                :class:`globaleaks.plugins.base.Event`).


        """
        events = []
        cplugin = GLSetting.notification_plugins[0]

        plugin = getattr(notification, cplugin)()

        not_notified_comments = store.find(models.Comment,
            models.Comment.mark == models.Comment._marker[0]
        )

        node_desc = admin.admin_serialize_node(store.find(models.Node).one(), GLSetting.memory_copy.default_language)

        if not_notified_comments.count():
            log.debug("Comments found to be notified: %d" % not_notified_comments.count() )

        for comment in not_notified_comments:

            if comment.internaltip is None or comment.internaltip.receivers is None:
                log.err("Comment %s has internaltip or receivers broken reference" % comment.id)
                comment.mark = models.Comment._marker[2] # 'unable to notify'
                continue

            # for every comment, iter on the associated receiver
            log.debug("Comments receiver: %d" % comment.internaltip.receivers.count())

            comment_desc = rtip.receiver_serialize_comment(comment)

            if not comment.internaltip.context:
                log.err("(comment_notification) Integrity check failure Context")
                continue

            context_desc = admin.admin_serialize_context(comment.internaltip.context, GLSetting.memory_copy.default_language)

            # XXX BUG! All notification is marked as correctly send,
            # This can't be managed by callback, and can't be managed by actual DB design
            comment.mark = models.Comment._marker[1] # 'notified'

            for receiver in comment.internaltip.receivers:

                receiver_desc = admin.admin_serialize_receiver(receiver, GLSetting.memory_copy.default_language)
                if not receiver_desc.has_key('mail_address'):
                    log.err("Receiver %s lack of email address!" % receiver.name)
                    continue

                # if the comment author is the one to be notified: skip the notification
                # ----- BUG, remind,
                # if two receiver has the same name, and one has notification disabled
                # also the homonymous would get the notification dropped.
                if comment._types == models.Comment._types[0] and comment.author == receiver.name:
                    log.debug("Receiver is the Author (%s): skipped" % receiver.user.username)
                    continue

                # check if the receiver has the Comment notification enabled or not
                if not receiver.comment_notification:
                    log.debug("Receiver %s has comment notification disabled: skipped [source: %s]" % (
                        receiver.user.username, comment.author))
                    continue

                event = Event(type=u'comment', trigger='Comment',
                    notification_settings=self.notification_settings,
                    trigger_info=comment_desc,
                    node_info=node_desc,
                    receiver_info=receiver_desc,
                    context_info=context_desc,
                    plugin=plugin)

                events.append(((unicode(comment.id), unicode(receiver.id)), event))

        return events

    @transact_ro
    def comment_notification_succeeded(self, store, result, comment_id, receiver_id):
        """
        This is called when the comment notification has succeeded
        """
        receiver = store.find(models.Receiver, models.Receiver.id == receiver_id).one()

        if not receiver:
            raise errors.ReceiverGusNotFound

        log.debug("Email: +[Success] Notification of comment receiver %s" % receiver.user.username)

    @transact_ro
    def comment_notification_failed(self, store, failure, comment_id, receiver_id):
        """
        This is called when the comment notification has failed.
        """
        receiver = store.find(models.Receiver, models.Receiver.id == receiver_id).one()

        if not receiver:
            raise errors.ReceiverGusNotFound

        log.debug("Email: -[Fail] Notification of comment receiver %s" % receiver.user.username)

    @inlineCallbacks
    def do_comment_notification(self, comment_events):
        for comment_receiver_id, event in comment_events:
            comment_id, receiver_id = comment_receiver_id

            notify = event.plugin.do_notify(event)
            notify.addCallback(self.comment_notification_succeeded, comment_id, receiver_id)
            notify.addErrback(self.comment_notification_failed, comment_id, receiver_id)

            # we need to wait on single mail send basis to not be prone to DoS
            # and be forced to open so many outgoing connections.
            yield notify

    @transact
    def create_file_notification_events(self, store):
        """
        Creates events for performing notification of newly added files..

        Returns:
            events: a list of tuples containing ((receiverfile_id, receiver_id), an instance of
                :class:`globaleaks.plugins.base.Event`).

        """
        events = []
        cplugin = GLSetting.notification_plugins[0]

        plugin = getattr(notification, cplugin)()

        not_notified_rfiles = store.find(models.ReceiverFile,
            models.ReceiverFile.mark == models.ReceiverFile._marker[0]
        )

        node_desc = admin.admin_serialize_node(store.find(models.Node).one(), GLSetting.memory_copy.default_language)

        if not_notified_rfiles.count():
            log.debug("Receiverfiles found to be notified: %d" % not_notified_rfiles.count() )

        for rfile in not_notified_rfiles:

            if not rfile.internalfile:
                log.err("(file_notification) Integrity check failure (InternalFile)")
                continue

            file_desc = serialize_internalfile(rfile.internalfile)

            if  not rfile.internalfile or \
                not rfile.internalfile.internaltip or \
                not rfile.internalfile.internaltip.context:
                log.err("(file_notification) Integrity check failure (File+Tip)")
                continue

            context_desc = admin.admin_serialize_context(rfile.internalfile.internaltip.context,
                GLSetting.memory_copy.default_language)

            receiver_desc = admin.admin_serialize_receiver(rfile.receiver, GLSetting.memory_copy.default_language)
            if not receiver_desc.has_key('mail_address'):
                log.err("Receiver %s lack of email address!" % rfile.receiver.user.name)
                continue

            # check if the receiver has the File notification enabled or not
            if not rfile.receiver.file_notification:
                log.debug("Receiver %s has file notification disabled: %s skipped" % (
                    rfile.receiver.user.username, rfile.internalfile.name ))
                rfile.mark = models.ReceiverFile._marker[3] # 'disabled'
                store.commit()
                continue

            # by ticket https://github.com/globaleaks/GlobaLeaks/issues/444
            # send notification of file only if notification of tip is already on send status
            if rfile.receiver_tip.mark == models.ReceiverTip._marker[0]: # 'not notified'
                rfile.mark = models.ReceiverFile._marker[4] # 'skipped'
                log.debug("Skipped notification of %s (for %s) because Tip not yet notified" %
                          (rfile.internalfile.name, rfile.receiver.name) )
                store.commit()
                continue

            event = Event(type=u'file', trigger='File',
                notification_settings=self.notification_settings,
                trigger_info=file_desc,
                node_info=node_desc,
                receiver_info=receiver_desc,
                context_info=context_desc,
                plugin=plugin)

            events.append(((unicode(rfile.id), unicode(rfile.receiver.id)), event))

        return events

    @transact
    def receiverfile_notification_succeeded(self, store, result, receiverfile_id, receiver_id):
        """
        This is called when the Receiver File notification has succeeded
        """
        rfile = store.find(models.ReceiverFile, models.ReceiverFile.id == receiverfile_id).one()

        if not rfile:
            raise errors.FileGusNotFound

        rfile.mark = models.ReceiverFile._marker[1] # 'notified'

        log.debug("Email: +[Success] Notification of receiverfile %s for receiver %s" % (rfile.internalfile.name, rfile.receiver.user.username))

    @transact
    def receiverfile_notification_failed(self, store, failure, receiverfile_id, receiver_id):
        """
        This is called when the Receiver File notification has failed.
        """
        rfile = store.find(models.ReceiverFile, models.ReceiverFile.id == receiverfile_id).one()

        if not rfile:
            raise errors.FileGusNotFound

        rfile.mark = models.ReceiverFile._marker[2] # 'unable to notify'

        log.debug("Email: -[Fail] Notification of receiverfile %s for receiver %s" % (rfile.internalfile.name, rfile.receiver.user.username))
    
    @inlineCallbacks
    def do_receiverfile_notification(self, receiverfile_events):
        for receiverfile_receiver_id, event in receiverfile_events:
            receiverfile_id, receiver_id = receiverfile_receiver_id

            notify = event.plugin.do_notify(event)
            notify.addCallback(self.receiverfile_notification_succeeded, receiverfile_id, receiver_id)
            notify.addErrback(self.receiverfile_notification_failed, receiverfile_id, receiver_id)

            # we need to wait on single mail send basis to not be prone to DoS
            # and be forced to open so many outgoing connections.
            yield notify

    @inlineCallbacks
    def operation(self):
        """
        Goal of this event is to check all the:
            Tips
            Comment
            New files
            System Event

        Only the Models with the 'notification_status' can track which elements has been
        notified or not.
        """
        try:
            # Initialize Notification setting system wide
            self.notification_settings = yield self._get_notification_settings()

            if not self.notification_settings:
                log.err("Node has not Notification configured, Notification disabled!")
                return

            if GLSetting.notification_temporary_disable:
                log.err("Node has Notification temporary disabled")
                return

            tip_events = yield self.create_tip_notification_events()
            comment_events = yield self.create_comment_notification_events()
            file_events = yield self.create_file_notification_events()
            message_events = yield self.create_message_notification_events()

        except Exception as excep:
            log.err("Error in notification event creation: %s" % excep)
            log.debug(sys.exc_info())
            return

        try:
            if tip_events:
                yield self.do_tip_notification(tip_events)
        except Exception as excep:
            log.err("Error in Tip notification: %s" % excep)
            log.debug(sys.exc_info())

        try:
            if comment_events:
                yield self.do_comment_notification(comment_events)
        except Exception as excep:
            log.err("Error in Comment notification: %s" % excep)
            log.debug(sys.exc_info())

        try:
            if file_events:
                yield self.do_receiverfile_notification(file_events)
        except Exception as excep:
            log.err("Error in File notification: %s" % excep)
            log.debug(sys.exc_info())
