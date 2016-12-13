import json
import logging
import re
import threading

import sseclient


class MarathonEvent(object):
    """
    Represens a single event from Marathon
    """
    def __init__(self, data):
        self.data = data

    def _get_event_type(self):
        """
        Gets the event type
        """
        if not 'eventType' in self.data:
            return 'UNKNOWN'
        return self.data['eventType']

    def app_id(self):
        """
        Gets the appId
        """
        return self.data['appId']

    def task_id(self):
        """
        Gets the taskId
        """
        return self.data['taskId']

    def slave_id(self):
        """
        Gets the slaveId
        """
        return self.data['slaveId']

    def _get_task_status(self):
        """
        Gets the task status
        """
        return self.data['taskStatus']

    def is_status_update(self):
        """
        True if event represents a status update
        """
        return self._get_event_type() == 'status_update_event'

    def is_task_failed(self):
        """
        True if task is failed, false otherwise
        """
        return self._get_task_status() == 'TASK_FAILED'

    def is_task_staging(self):
        """
        True if task is staging, false otherwise
        """
        return self._get_task_status() == 'TASK_STAGING'

    def is_task_running(self):
        """
        True if task is running, false otherwise
        """
        return self._get_task_status() == 'TASK_RUNNING'

    def is_task_killed(self):
        """
        True if task is killed, false otherwise
        """
        return self._get_task_status() == 'TASK_KILLED'

    def is_deployment_succeeded(self):
        """
        True if event represents a successful deployment
        """
        return self._get_event_type() == 'deployment_success'

    def is_deployment_failed(self):
        """
        True if event represents a failed deployment
        """
        return self._get_event_type() == 'deployment_failed'

    def status(self):
        """
        Gets the event status
        """
        event_status = ""
        if self.is_task_running():
            event_status = 'Service "{}" is running'.format(self.app_id())
        elif self.is_task_staging():
            event_status = 'Service "{}" is being staged'.format(self.app_id())
        elif self.is_task_failed():
            event_status = 'Service "{}" has failed: {}'.format(
                self.app_id(), self.data['message'])
        elif self.is_task_killed():
            event_status = 'Service "{}" was killed: {}'.format(
                self.app_id(), self.data['message'])
        return event_status

class DeploymentMonitor(object):
    """
    Monitors deployment of apps to Marathon using their
    app IDs
    """
    def __init__(self, marathon, app_ids, deployment_id):
        self._marathon = marathon
        self._deployment_failed = False
        self._deployment_succeeded = False
        self._app_ids = app_ids
        self._deployment_id = deployment_id
        self._stop_event = threading.Event()
        self._failed_event = None
        self._failure_message = None
        self._thread = threading.Thread(
            target=DeploymentMonitor._process_events, args=(self,))

    def start(self):
        """
        Starts the deployment monitor
        """
        self._thread.daemon = True
        self._thread.start()

    def stop(self):
        """
        Stops the deployment monitor
        """
        self._stop_event.set()
        self._thread.join()

    def is_running(self):
        """
        True if monitor is running, false otherwise.
        """
        return not self._stop_event.is_set()

    def get_failed_event(self):
        """
        Gets the last failed event
        """
        return self._failed_event

    def get_failure_message(self):
        """
        Gets the failure message
        """
        return self._failure_message

    def deployment_failed(self):
        """
        True if deployment failed, false otherwise
        """
        return self._deployment_failed

    def deployment_succeeded(self):
        """
        True if deployment succeeded, false otherwise
        """
        return self._deployment_succeeded

    def _process_events(self):
        """
        Reads the event stream from Marathon and handles events
        """
        events = self._get_event_stream()
        for event in events:
            try:
                if self._stop_event.is_set():
                    break
                if self._handle_event(event):
                    self.stop()
                    break
            except:
                # Ignore any exceptions
                pass

    def _handle_event(self, event):
        """
        Handles single event from Marathon by logging it
        and/or signaling to stop the deployment monitor
        """
        deployment_finished = False
        if event.is_status_update():
            if event.app_id() in self._app_ids:
                # Log the event information
                logging.info(event.status())
                if event.is_task_failed() or event.is_task_killed():
                    self._deployment_failed = True
                    self._failed_event = event
                    deployment_finished = True
        elif event.is_deployment_succeeded():
            if self._deployment_id == event.data['id']:
                self._deployment_succeeded = True
                deployment_finished = True
        elif event.is_deployment_failed():
            if self._deployment_id == event.data['id']:
                self._deployment_failed = True
                self._failure_message = 'Deployment failed.'
                deployment_finished = True
        return deployment_finished

    def _get_event_stream(self):
        """
        Gets the event stream by making a GET request to
        Marathon /events endpoint
        """
        events_url = self._marathon.get_url('service/marathon/v2/events')
        messages = sseclient.SSEClient(events_url)
        for msg in messages:
            event = MarathonEvent(json.loads(msg.data))
            yield event
