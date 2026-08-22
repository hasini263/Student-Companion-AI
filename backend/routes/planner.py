from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models.study_plan import StudyPlan
from extensions import db
from routes.notes import extract_pdf_text
from services.ai_service import generate_study_plan, generate_study_plan_from_syllabus
import io
import json

planner_bp = Blueprint("planner", __name__)

@planner_bp.route("/generate", methods=["POST"])
@jwt_required()
def generate():
    try:
        raw_identity = get_jwt_identity()
        user_id = int(raw_identity)
        
        # Check if a syllabus file is uploaded
        if 'file' in request.files:
            file = request.files['file']
            if file.filename == '':
                return jsonify({"message": "Empty file uploaded"}), 400
            if not file.filename.lower().endswith('.pdf'):
                return jsonify({"message": "Only PDF syllabus papers are supported"}), 400
                
            file_stream = io.BytesIO(file.read())
            extracted_content, error_msg = extract_pdf_text(file_stream)
            if error_msg or not extracted_content:
                return jsonify({"message": f"Failed to parse PDF syllabus: {error_msg or 'No text found'}"}), 400

            exam_dates = request.form.get("exam_dates") or "Upcoming Exams"
            subjects = request.form.get("subjects") or file.filename.rsplit('.', 1)[0]
            
            # Generate plan based on the syllabus content
            schedule = generate_study_plan_from_syllabus(extracted_content, exam_dates)
        else:
            # Fall back to JSON or Form request data
            data = request.get_json(silent=True) or {}
            subjects = data.get("subjects") or request.form.get("subjects")
            exam_dates = data.get("exam_dates") or request.form.get("exam_dates") or "Upcoming Exams"
            
            if not subjects:
                return jsonify({"message": "Subjects or syllabus file is required"}), 400
                
            # Generate schedule from subjects list
            schedule = generate_study_plan(subjects, exam_dates)
        
        if not schedule or not isinstance(schedule, list):
            schedule = generate_study_plan(subjects or "General Study", exam_dates)

        # Delete previous study plan(s) to replace with the new one
        existing_plans = StudyPlan.query.filter_by(user_id=user_id).all()
        for p in existing_plans:
            db.session.delete(p)
            
        new_plan = StudyPlan(
            user_id=user_id,
            subjects=str(subjects),
            exam_dates=str(exam_dates),
            schedule_json=json.dumps(schedule)
        )
        
        db.session.add(new_plan)
        db.session.commit()
        
        return jsonify({
            "message": "Study plan generated and saved",
            "plan": {
                "id": new_plan.id,
                "subjects": new_plan.subjects,
                "exam_dates": new_plan.exam_dates,
                "schedule": schedule,
                "created_at": new_plan.created_at.isoformat()
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        print(f"Error in planner generate route: {e}")
        return jsonify({"message": f"Server error generating study plan: {str(e)}"}), 500


@planner_bp.route("", methods=["GET"])
@jwt_required()
def get_plan():
    try:
        user_id = int(get_jwt_identity())
        plan = StudyPlan.query.filter_by(user_id=user_id).order_by(StudyPlan.created_at.desc()).first()
    except Exception:
        return jsonify(None), 200

    
    if not plan:
        return jsonify(None), 200
        
    try:
        schedule_parsed = json.loads(plan.schedule_json)
    except Exception:
        schedule_parsed = []
        
    return jsonify({
        "id": plan.id,
        "subjects": plan.subjects,
        "exam_dates": plan.exam_dates,
        "schedule": schedule_parsed,
        "created_at": plan.created_at.isoformat()
    }), 200
