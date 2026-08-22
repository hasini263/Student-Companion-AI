import os
import json
import requests
import re
from dotenv import load_dotenv


load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")


def _is_error_response(text):
    """
    Detects provider error messages (e.g. text-only models rejecting image input)
    so they can be treated as a failure and trigger the offline fallback.
    """
    if not text:
        return False
    lowered = text.lower()
    markers = [
        "does not support image",
        "cannot read",
        "image input",
        "unsupported image",
        '"error"',
        "error:",
    ]
    return any(m in lowered for m in markers)


def call_ollama_api(prompt):
    """
    Calls a locally running Ollama server and returns the generated text response.
    Returns None on any failure (network, HTTP error, or model error) so the
    caller can fall back to the offline generator.
    """
    try:
        url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3}
        }
        response = requests.post(url, json=payload, timeout=90)
        if response.status_code == 200:
            res_data = response.json()
            # Ollama may return 200 with an "error" key on invalid requests
            if "error" in res_data:
                print(f"Ollama API Error: {res_data['error']}")
                return None
            text = res_data.get("response", "").strip()
            # Reject raw provider errors (e.g. image sent to a text-only model)
            if _is_error_response(text):
                print(f"Ollama returned an error response: {text}")
                return None
            return text
        print(f"Ollama API Error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"Exception during Ollama API call: {e}")
    return None


def call_ai(prompt):
    """
    Uses Ollama locally for all AI generation tasks.
    """
    return call_ollama_api(prompt)

def generate_summary(text):
    """
    Summarizes the provided notes/text.
    """
    prompt = (
        f"You are an expert AI notes summarizer. Analyze the following study material and generate a structured summary. "
        f"Include a 'Key Concepts' section, a list of 'Important Terms', and a detailed 'Bulleted Summary'. "
        f"Keep the language clear, academic, and extremely readable.\n\n"
        f"Study Material:\n{text[:8000]}"
    )
    
    response = call_ai(prompt)
    if response:
        return response
        
    # Heuristic Fallback Summarizer
    words = text.split()
    title_words = [w.capitalize() for w in words[:min(5, len(words))] if len(w) > 3]
    topic = " ".join(title_words) if title_words else "Study Subject"
    
    summary_md = f"""# Summary: {topic}

## 📌 Key Concepts
- **Core Subject Matter**: Analysis of input material relating to "{topic}".
- **Information Retrieval**: Organizes information into chunk-sized units for better comprehension.
- **Academic Focus**: Tailored notes highlight structure, terms, and conceptual definitions.

## 📖 Important Terms
- **{topic or "Subject"}**: The primary focus of the uploaded study document.
- **Synthesis**: The combination of ideas to form a theory or system.
- **Retention**: The ability to recall or retain knowledge in memory over time.

## 📝 Bulleted Summary
- The provided study notes contain {len(words)} words focusing on key details of the curriculum.
- Main point 1: This document outlines the structural foundation of the subject matter.
- Main point 2: It is highly recommended to review vocabulary and key equations regularly.
- Main point 3: Practice with active recall and quiz testing will ensure optimal exam performance.
"""
    return summary_md

def generate_quiz(topic, count=5):
    """
    Generates interactive quiz questions for a given topic.
    Returns a list of dictionaries with 'question', 'options', 'correctAnswer' (index).
    """
    prompt = (
        f"Generate a multiple-choice quiz about '{topic}' with exactly {count} questions. "
        f"Return ONLY a JSON array of objects. Do not include any markdown format tags or backticks (e.g. do not wrap in ```json). "
        f"Each object must have the following keys:\n"
        f"- 'question': the question text\n"
        f"- 'options': an array of 4 strings representing the options\n"
        f"- 'correctAnswer': the 0-indexed integer of the correct option\n"
        f"Example:\n"
        f"[{{\"question\": \"What is 2+2?\", \"options\": [\"3\", \"4\", \"5\", \"6\"], \"correctAnswer\": 1}}]"
    )
    
    response = call_ai(prompt)
    if response:
        try:
            # Clean possible markdown wrap in Gemini response
            cleaned_resp = response.strip()
            if cleaned_resp.startswith("```json"):
                cleaned_resp = cleaned_resp[7:]
            if cleaned_resp.endswith("```"):
                cleaned_resp = cleaned_resp[:-3]
            cleaned_resp = cleaned_resp.strip()
            questions = json.loads(cleaned_resp)
            if isinstance(questions, list) and len(questions) > 0:
                return questions
        except Exception as e:
            print(f"Failed to parse Gemini quiz JSON: {e}. Raw response: {response}")
            
    return _fallback_quiz(topic, count)


def _fallback_quiz(topic, count=5):
    """Offline quiz generator used when the LLM is unavailable."""
    fallback_quizzes = {
        "operating systems": [
            {"question": "What is the main purpose of an Operating System?", "options": ["To compile code", "To act as an intermediary between user and hardware", "To connect to the internet", "To design graphics"], "correctAnswer": 1},
            {"question": "Which of the following is NOT an operating system?", "options": ["Windows", "Linux", "Python", "macOS"], "correctAnswer": 2},
            {"question": "What is virtual memory?", "options": ["Memory on a flash drive", "Hardware RAM module", "Temporary memory storage using hard disk space", "Cache memory"], "correctAnswer": 2},
            {"question": "What is a deadlock in OS?", "options": ["A virus infection", "A situation where processes are blocked waiting for resources", "A computer crash", "Slow file retrieval"], "correctAnswer": 1},
            {"question": "Which scheduling algorithm assigns equal time slices to each process?", "options": ["First Come First Served", "Shortest Job First", "Round Robin", "Priority Scheduling"], "correctAnswer": 2}
        ],
        "default": [
            {"question": f"What is the primary definition of {topic}?", "options": ["A theoretical concept in science", "The systematic study of its processes and systems", "An application software tool", "None of the above"], "correctAnswer": 1},
            {"question": f"Which component is most critical to understanding {topic}?", "options": ["Theoretical research foundations", "Empirical data analysis", "System design and implementation", "All of the above"], "correctAnswer": 3},
            {"question": f"What is a common misconception about {topic}?", "options": ["It is easily understood without practice", "It is only studied in colleges", "It does not apply to real-world tasks", "It is fully automated by machines"], "correctAnswer": 0},
            {"question": f"Which term is closely associated with {topic}?", "options": ["Structured analysis", "Random guessing", "Static evaluation", "Manual scheduling"], "correctAnswer": 0},
            {"question": f"Why is {topic} taught in modern education?", "options": ["To increase computer usage", "To build foundational and problem-solving skills", "To satisfy registration requirements", "To teach keyboard typing speed"], "correctAnswer": 1}
        ]
    }

    key = (topic or "").lower().strip()
    if key in fallback_quizzes:
        return list(fallback_quizzes[key])[:count]
    return list(fallback_quizzes["default"])[:count]


def generate_quiz_from_text(text, subject="", topic="", count=5):
    """
    Generates multiple-choice quiz questions from extracted PDF/notes text.
    Returns a list of dicts with 'question', 'options' (4 strings), 'correctAnswer' (0-indexed int).
    Falls back to the offline generator when the LLM is unavailable.
    """
    label = topic or subject or "the uploaded study material"
    context = (text or "").strip()

    if context:
        prompt = (
            f"You are an expert teacher. Create a multiple-choice quiz from the following study notes "
            f"about '{label}'. Generate exactly {count} questions.\n"
            f"Return ONLY a JSON array of objects. Do not include markdown code block tags or backticks. "
            f"Each object must have the following keys:\n"
            f"- 'question': the question text\n"
            f"- 'options': an array of exactly 4 strings (options a-d)\n"
            f"- 'correctAnswer': the 0-indexed integer of the correct option\n"
            f"Study Notes:\n{context[:8000]}\n\n"
            f"Example:\n"
            f"[{{\"question\": \"What is 2+2?\", \"options\": [\"3\", \"4\", \"5\", \"6\"], \"correctAnswer\": 1}}]"
        )
        response = call_ai(prompt)
        if response:
            try:
                cleaned = response.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()
                questions = json.loads(cleaned)
                if isinstance(questions, list) and len(questions) > 0:
                    return questions
            except Exception as e:
                print(f"Failed to parse generated quiz JSON: {e}. Raw response: {response}")

    return _fallback_quiz(label, count)

def generate_study_plan(subjects, exam_dates):
    """
    Generates a structured weekly study plan schedule based on subjects and exam dates.
    Returns a list of dicts with 'day', 'subject', 'topic', 'duration', 'priority'.
    """
    if isinstance(subjects, list):
        subjects = ", ".join(str(s) for s in subjects)
    subjects = str(subjects or "General Study")
    exam_dates = str(exam_dates or "Upcoming Exams")

    prompt = (
        f"Generate a customized study plan for these subjects: '{subjects}' and corresponding exam dates: '{exam_dates}'. "
        f"Return ONLY a JSON array of objects. Do not include markdown code block tags. "
        f"Each object must have the following keys:\n"
        f"- 'day': Day name (e.g. Monday, Tuesday)\n"
        f"- 'subject': The subject name\n"
        f"- 'topic': Specific topic to study\n"
        f"- 'duration': Study time (e.g. '2 Hours')\n"
        f"- 'priority': Priority level ('High', 'Medium', 'Low')\n"
        f"Example:\n"
        f"[{{\"day\": \"Monday\", \"subject\": \"Math\", \"topic\": \"Calculus Integrals\", \"duration\": \"2.5 Hours\", \"priority\": \"High\"}}]"
    )
    
    response = call_ai(prompt)
    if response:
        try:
            cleaned_resp = response.strip()
            if cleaned_resp.startswith("```json"):
                cleaned_resp = cleaned_resp[7:]
            if cleaned_resp.endswith("```"):
                cleaned_resp = cleaned_resp[:-3]
            cleaned_resp = cleaned_resp.strip()
            plan = json.loads(cleaned_resp)
            if isinstance(plan, list) and len(plan) > 0:
                return plan
        except Exception as e:
            print(f"Failed to parse Gemini study plan JSON: {e}")

    # Fallback Planner
    subj_list = [s.strip() for s in subjects.split(",") if s.strip()]
    if not subj_list:
        subj_list = ["Core Study Subject"]

    
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    schedule = []
    
    topics = {
        "math": ["Linear Algebra", "Calculus & Limits", "Probability distributions", "Statistical inference"],
        "science": ["Newton's Laws", "Chemical Bonding", "Cell Division", "Thermodynamics"],
        "history": ["World War I", "The Industrial Revolution", "Ancient Civilizations", "Colonial America"],
        "computer science": ["Data Structures", "Algorithm complexity", "Operating System Processes", "Database Queries"],
        "default": ["Introductory Concepts", "Advanced Application Problems", "Mock Practice Questions", "Past Exam Paper Review"]
    }

    for idx, day in enumerate(days):
        subject = subj_list[idx % len(subj_list)]
        subj_key = subject.lower().strip()
        
        # Get topic lists
        topic_pool = topics.get(subj_key, topics["default"])
        topic = topic_pool[idx % len(topic_pool)]
        
        schedule.append({
            "day": day,
            "subject": subject,
            "topic": topic,
            "duration": "2.5 Hours" if idx % 2 == 0 else "1.5 Hours",
            "priority": "High" if idx % 3 == 0 else "Medium"
        })
        
    return schedule

def generate_study_plan_from_syllabus(syllabus_text, exam_dates):
    """
    Generates a structured weekly study plan schedule based on syllabus contents and exam dates.
    Returns a list of dicts.
    """
    prompt = (
        f"You are an expert AI study planner. Analyze the following course syllabus and design a structured weekly study plan. "
        f"Keep the exam dates / target deadlines in mind: '{exam_dates}'.\n\n"
        f"Syllabus Content:\n{syllabus_text[:6000]}\n\n"
        f"Return ONLY a JSON array of objects. Do not include markdown code block tags. "
        f"Each object must have the following keys:\n"
        f"- 'day': Day name (e.g. Monday, Tuesday)\n"
        f"- 'subject': The subject or course name\n"
        f"- 'topic': Specific topic/unit module to study from the syllabus\n"
        f"- 'duration': Study time (e.g. '2 Hours')\n"
        f"- 'priority': Priority level ('High', 'Medium', 'Low')\n"
        f"Example:\n"
        f"[{{\"day\": \"Monday\", \"subject\": \"Math\", \"topic\": \"Calculus Integrals\", \"duration\": \"2.5 Hours\", \"priority\": \"High\"}}]"
    )
    
    response = call_ai(prompt)
    if response:
        try:
            cleaned_resp = response.strip()
            if cleaned_resp.startswith("```json"):
                cleaned_resp = cleaned_resp[7:]
            if cleaned_resp.endswith("```"):
                cleaned_resp = cleaned_resp[:-3]
            cleaned_resp = cleaned_resp.strip()
            plan = json.loads(cleaned_resp)
            if isinstance(plan, list) and len(plan) > 0:
                return plan
        except Exception as e:
            print(f"Failed to parse syllabus study plan JSON: {e}")
            
    # Fallback if AI call or JSON parsing fails
    words = syllabus_text.split()
    subjects = " ".join([w.capitalize() for w in words[:min(3, len(words))] if len(w) > 3]) or "Syllabus Core Topics"
    return generate_study_plan(subjects, exam_dates)


def generate_chat_reply(query, context_list, recent_history=None):
    """
    Generates an educational explanation as a smart AI Chatbot, incorporating RAG context if available.
    """
    # Detect simple user greetings and return a friendly welcome message instantly
    query_clean = query.lower().strip().replace("?", "").replace("!", "")
    greetings = {"hi", "hello", "hey", "greetings", "good morning", "good afternoon", "good evening", "yo", "hello there", "haii", "hai", "hay", "hii", "hiii"}
    is_user_greeting = query_clean in greetings or (len(query_clean.split()) <= 2 and any(query_clean.startswith(g) for g in ["hi", "hello", "hey", "hai"]))

    if is_user_greeting:
        return "Hello! How can I help you with your studies or questions today?"

    # Format retrieved RAG context notes if available
    formatted_contexts = []
    if context_list:
        for idx, item in enumerate(context_list, 1):
            if isinstance(item, dict):
                title = item.get("title", "Study Note")
                content = item.get("content", "")
                formatted_contexts.append(f"[Document #{idx}: {title}]\n{content}")
            else:
                formatted_contexts.append(f"[Document #{idx}]\n{item}")

    context_text = "\n\n".join(formatted_contexts) if formatted_contexts else ""

    # Format previous session messages
    history_text = ""
    if recent_history:
        history_lines = []
        for turn in recent_history:
            history_lines.append(f"Student: {turn.get('query')}\nAssistant: {turn.get('response')}")
        history_text = "\n\n".join(history_lines)

    # Prompt construction
    prompt_parts = ["You are 'Student Companion', a helpful, intelligent educational AI assistant."]
    
    if history_text:
        prompt_parts.append(f"Previous Conversation History:\n{history_text}")

    if context_text:
        prompt_parts.append(
            f"Relevant Study Notes Context:\n{context_text}\n\n"
            f"Instructions: Use the study notes context above to help answer the question accurately whenever relevant."
        )

    prompt_parts.append(
        f"User Question: {query}\n\n"
        f"Instructions: Provide a clear, thorough, academic, and well-structured response with code examples or bullet points where helpful."
    )
    
    full_prompt = "\n\n".join(prompt_parts)

    response = call_ai(full_prompt)
    if response:
        return response

    # ----------------------------------------------------
    # RAG PDF Answer Synthesizer (Extracts from uploaded PDF)
    # ----------------------------------------------------
    if context_list:
        source_title = context_list[0].get("title", "Uploaded PDF Notes") if isinstance(context_list[0], dict) else "Uploaded PDF Notes"
        
        # Clean and collect text from all retrieved chunks
        cleaned_chunks = []
        for item in context_list:
            raw_text = item.get("content", "") if isinstance(item, dict) else str(item)
            # Remove PDF headers, URLs, and artifact noise
            lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
            valid_lines = [
                l for l in lines 
                if not any(noise in l.lower() for noise in ["www.jntufastupdates", "page ", "http://", "https://"])
                and len(l) > 3
            ]
            cleaned = "\n".join(valid_lines)
            if cleaned and cleaned not in cleaned_chunks:
                cleaned_chunks.append(cleaned)

        full_extracted_text = "\n\n".join(cleaned_chunks)
        # Strip noisy prefix fragments (e.g. 'gh', 'method calls.')
        full_extracted_text = re.sub(r'^(?:gh\b|method calls\.|\b[a-z]{1,2}\b\s+)+', '', full_extracted_text, flags=re.IGNORECASE).strip()

        reply = f"### 📚 Answer from **{source_title}**\n\n"

        reply += f"Here is the detailed explanation extracted directly from your uploaded PDF (**{source_title}**):\n\n"

        # Separate code snippets and text paragraphs
        code_snippets = re.findall(r'(?:public class|class |public static void|void |\bdef\b)[\s\S]*?\n\}', full_extracted_text)
        
        raw_paragraphs = [p.strip() for p in full_extracted_text.split("\n\n") if len(p.strip()) > 15]

        # Section 1: Overview & Definition
        reply += f"#### 📌 Key Concept & Definition\n"
        main_paragraphs = []
        for p in raw_paragraphs:
            if not any(kw in p for kw in ["public class", "public static void", "class ThisDemo"]):
                main_paragraphs.append(" ".join(p.split()))

        if main_paragraphs:
            for p in main_paragraphs[:3]:
                reply += f"- {p}\n\n"
        elif raw_paragraphs:
            reply += f"- {' '.join(raw_paragraphs[0].split())}\n\n"

        # Section 2: Code Structure & Implementation (if present in PDF)
        if code_snippets:
            reply += f"#### 💻 Program Structure & Code Example from PDF\n```java\n"
            reply += f"{code_snippets[0].strip()}\n```\n\n"

        # Section 3: Additional Notes & Details
        if len(main_paragraphs) > 3:
            reply += f"#### 📖 Detailed Information from Document\n"
            for p in main_paragraphs[3:7]:
                reply += f"• {p}\n\n"

        reply += f"---\n*Source: Synthesized directly from your uploaded PDF notes (`{source_title}`).*"
        return reply


    # Fallback for general queries when no PDF notes match
    reply = ""
    low_query = query.lower()
    if "virtual memory" in low_query:
        reply += """**Virtual Memory** is a memory management technique that gives a process the impression that it has contiguous working memory, even if it is fragmented or stored partially on secondary disk storage.

#### Core Principles:
1. **Paging**: Memory is divided into fixed-size blocks called *pages* (virtual) and *frames* (physical RAM).
2. **Page Table**: Translates virtual memory addresses to physical RAM addresses.
3. **Page Fault**: Occurs when a requested page is not in RAM; the OS fetches it from secondary storage.
4. **Thrashing**: Occurs when excessive paging leads to severe performance degradation.

#### Benefits:
- Allows running applications larger than physical RAM.
- Provides process isolation and security."""
    elif "operating system" in low_query or "os" in low_query or "deadlock" in low_query:
        reply += """An **Operating System (OS)** manages system hardware, processes, memory, and file systems.

#### Key Functions:
- **Process Management**: CPU scheduling (Round Robin, FCFS, Priority).
- **Memory Management**: RAM allocation, virtual memory, and garbage collection.
- **Deadlock Handling**: Requires 4 Coffman conditions (Mutual Exclusion, Hold & Wait, No Preemption, Circular Wait)."""
    elif "red black" in low_query or ("tree" in low_query and "binary" in low_query):
        reply += """**Red-Black Tree** is a self-balancing binary search tree where every node has a color attribute (red or black).

#### Key Properties:
1. The root node is always **Black**.
2. Red nodes cannot have Red children (No two consecutive Red nodes).
3. Every path from a node to any of its descendant `null` pointers contains the exact same number of **Black** nodes.
4. Lookup, Insertion, and Deletion run in $O(\log n)$ worst-case time."""
    elif "java" in low_query:
        reply += """**Java** is a high-level, class-based, object-oriented programming language designed to have as few implementation dependencies as possible.

#### Core Features:
1. **Platform Independence (WORA)**: Compiled into bytecode that runs on the Java Virtual Machine (JVM).
2. **Object-Oriented**: Encapsulation, Inheritance, Polymorphism, and Abstraction.
3. **Automatic Garbage Collection**: Memory management handled by the JVM."""
    elif "ai" in low_query or "artificial intelligence" in low_query or "machine learning" in low_query:
        reply += """**Artificial Intelligence (AI)** refers to the simulation of human intelligence in machines programmed to think, learn, solve problems, and make decisions.

#### Key Subfields of AI:
1. **Machine Learning (ML)**: Algorithms that learn patterns from data (Supervised, Unsupervised, Reinforcement Learning).
2. **Deep Learning & Neural Networks**: Multi-layer neural networks used for complex data (images, voice, natural language).
3. **Natural Language Processing (NLP)**: Enables computers to understand, interpret, and generate human language.
4. **Computer Vision**: Allows machines to extract information from images and video streams."""
    elif "database" in low_query or "sql" in low_query or "dbms" in low_query:
        reply += """A **Database Management System (DBMS)** is software that stores, retrieves, and manages structured data.

#### Key Concepts:
1. **Relational Databases (RDBMS)**: Uses tables with rows and columns (e.g., PostgreSQL, MySQL, SQLite). Uses SQL for queries.
2. **ACID Properties**: Atomicity, Consistency, Isolation, and Durability ensure reliable transaction processing."""
    elif "python" in low_query or "code" in low_query or "program" in low_query:
        reply += """Here is a Python example illustrating clean code and problem solving:

```python
def binary_search(arr, target):
    low, high = 0, len(arr) - 1
    while low <= high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
This runs in $O(\log n)$ logarithmic time."""
    else:
        # Direct educational overview
        reply += f"### Explanation for **\"{query}\"**\n\n"
        if context_list:
            first_content = context_list[0].get("content", "") if isinstance(context_list[0], dict) else context_list[0]
            words = [w for w in re.findall(r'\b\w+\b', first_content) if len(w) > 4][:12]
            key_concepts = ", ".join(words[:5]) if words else "core principles"
            reply += f"Based on the subject material (**{key_concepts}**), here is the detailed breakdown:\n\n"
        else:
            reply += f"Here is the breakdown for your question:\n\n"

        reply += f"1. **Core Concept**: Understanding the primary terms and rules governing `{query}`.\n"
        reply += f"2. **Key Mechanism**: How this operates or is applied in practice.\n"
        reply += f"3. **Summary**: Key takeaways to remember for exams and assignments."

    return reply


