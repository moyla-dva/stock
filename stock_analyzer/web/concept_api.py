"""Stock concept API handlers."""

import logging

from flask import request

LOGGER = logging.getLogger(__name__)


def refresh_stock_concepts_response(jsonify, concept_job_manager, stock_service, logger):
    try:
        data = request.get_json(silent=True) or {}
        max_concepts = data.get("max_concepts")
        job = concept_job_manager.start_job(
            lambda max_concepts=None, progress_callback=None: stock_service.refresh_stock_concepts(
                max_concepts=max_concepts,
                logger=logger,
                progress_callback=progress_callback,
            ),
            max_concepts=max_concepts,
        )
        return jsonify(job), 202
    except Exception as exc:
        LOGGER.debug("股票概念刷新异常: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


def stock_concepts_status_response(jsonify, concept_job_manager, stock_service):
    try:
        return jsonify({
            "cache": stock_service.get_stock_concepts_status(),
            "job": concept_job_manager.current_job(),
        })
    except Exception as exc:
        LOGGER.debug("股票概念状态异常: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


def stock_concept_job_response(jsonify, concept_job_manager, job_id):
    job = concept_job_manager.get_job(job_id)
    if job is None:
        return jsonify({"error": "概念刷新任务不存在"}), 404
    return jsonify(job)
