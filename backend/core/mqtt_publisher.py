# -*- coding: utf-8 -*-
"""
MQTT Publisher utility for real-time notifications.
Publishes knowledge sync events to MQTT broker so Electron clients can refresh.
"""
import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

_client = None
_lock = threading.Lock()


def _get_client():
    """Lazy-initialize a singleton MQTT client."""
    global _client
    if _client is not None:
        return _client

    with _lock:
        if _client is not None:
            return _client
        try:
            import paho.mqtt.client as mqtt

            host = os.environ.get('MQTT_HOST', 'mqtt')
            port = int(os.environ.get('MQTT_PORT', 1883))

            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            client.connect(host, port, keepalive=60)
            client.loop_start()
            _client = client
            logger.info(f'[MQTT] Connected to {host}:{port}')
        except Exception as e:
            logger.warning(f'[MQTT] Failed to connect: {e}')
            return None
    return _client


def publish_knowledge_sync(shop_id, action, knowledge_id):
    """
    Publish a knowledge sync notification to MQTT.

    Args:
        shop_id: The shop ID (used as topic suffix)
        action: One of 'create', 'update', 'delete'
        knowledge_id: The knowledge base entry ID
    """
    if not shop_id:
        return

    try:
        client = _get_client()
        if client is None:
            return

        topic = f'knowledge/sync/{shop_id}'
        payload = json.dumps({
            'action': action,
            'knowledge_id': knowledge_id,
            'shop_id': str(shop_id),
        })
        client.publish(topic, payload, qos=1)
        logger.info(f'[MQTT] Published {action} to {topic}')
    except Exception as e:
        logger.warning(f'[MQTT] Publish failed: {e}')
