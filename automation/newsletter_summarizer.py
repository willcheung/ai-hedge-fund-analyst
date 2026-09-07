#!/usr/bin/env python3
"""
Newsletter Summarizer
Fetches newsletters from Gmail (tagged "newsletters"), summarizes by themes,
and saves daily briefing using Gemini for AI summarization.
"""
from automation_paths import configured_text

import os
import json
import base64
import re
from datetime import datetime, timedelta

from private_config import required_value

# Fail before SDK initialization, credential reads or delivery.
TARGET_EMAIL = required_value("NEWSLETTER_TARGET_EMAIL")
TOKEN_FILE = required_value("NEWSLETTER_TOKEN_FILE")
CLIENT_SECRETS = required_value("NEWSLETTER_CLIENT_SECRETS_FILE")

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google import genai
from google.genai import types
from json_repair import repair_json as json_repair_lib

# Configuration
NEWSLETTER_LABEL = 'newsletters'
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL=os.environ.get('GEMINI_MODEL', 'gemini-3.1-flash-lite-preview')

# Priority newsletters - always featured prominently (content creation sources)
PRIORITY_NEWSLETTERS = [s.strip() for s in os.environ.get("NEWSLETTER_PRIORITY_SENDERS", "").split(",") if s.strip()]

# Initialize Gemini client (new google.genai SDK)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

def get_credentials():
    """Get Gmail API credentials using refresh token."""
    with open(TOKEN_FILE, 'r') as f:
        token_data = json.load(f)

    with open(CLIENT_SECRETS, 'r') as f:
        client_secrets = json.load(f)

    client_id = client_secrets['installed']['client_id']
    client_secret = client_secrets['installed']['client_secret']

    creds = Credentials(
        token=token_data['access_token'],
        refresh_token=token_data['refresh_token'],
        token_uri=client_secrets['installed']['token_uri'],
        client_id=client_id,
        client_secret=client_secret,
        scopes=token_data['scope'].split(' ')
    )

    if creds.expired:
        creds.refresh(google.auth.transport.requests.Request())
        token_data['access_token'] = creds.token
        with open(TOKEN_FILE, 'w') as f:
            json.dump(token_data, f, indent=2)

    return creds

def authenticate_gmail():
    """Authenticate with Gmail API."""
    try:
        creds = get_credentials()
        service = build('gmail', 'v1', credentials=creds)
        return service
    except Exception as e:
        print(f"Authentication error: {e}")
        return None

def get_newsletters(service, hours_back=24):
    """Fetch newsletters from last N hours."""
    cutoff_time = (datetime.now() - timedelta(hours=hours_back)).strftime('%Y/%m/%d')
    query = f'label:{NEWSLETTER_LABEL} after:{cutoff_time}'

    print(f"Searching for newsletters: {query}")

    try:
        results = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=100
        ).execute()

        messages = results.get('messages', [])
        print(f"Found {len(messages)} messages")

        newsletters = []
        for msg in messages:
            msg_data = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='full'
            ).execute()

            content = extract_email_content(msg_data)
            sender = extract_sender(msg_data)
            subject = extract_subject(msg_data)
            date = extract_date(msg_data)

            # Extract sender email for priority check
            sender_email = ""
            headers = msg_data['payload'].get('headers', [])
            for header in headers:
                if header['name'].lower() == 'from':
                    from_val = header['value']
                    if '<' in from_val and '>' in from_val:
                        sender_email = from_val.split('<')[1].split('>')[0]
                    else:
                        sender_email = from_val
                    break

            newsletters.append({
                'id': msg['id'],
                'sender': sender,
                'sender_email': sender_email,
                'subject': subject,
                'date': date,
                'content': content,
            })

        return newsletters

    except HttpError as error:
        print(f"Gmail API error: {error}")
        return []

def extract_email_content(msg_data):
    """Extract and clean email content."""
    payload = msg_data['payload']
    parts = payload.get('parts', [])

    text_content = ""
    html_content = ""

    def extract_parts(parts_list):
        nonlocal text_content, html_content
        for part in parts_list:
            mime_type = part.get('mimeType', '')
            data = part.get('body', {}).get('data', '')

            if mime_type == 'text/plain' and data:
                text_content = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            elif mime_type == 'text/html' and data:
                html_content = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

            # Check nested parts
            subparts = part.get('parts', [])
            if subparts:
                extract_parts(subparts)

    if parts:
        extract_parts(parts)
    else:
        data = payload['body'].get('data', '')
        if data:
            text_content = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

    return clean_content(text_content if text_content else html_content)

def clean_content(content):
    """Clean up email content."""
    lines = content.split('\n')
    cleaned_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if 'view in browser' in line.lower() or 'view this post on the web' in line.lower():
            continue
        if 'unsubscribe' in line.lower():
            continue
        if line.startswith('http') or line.startswith('www'):
            continue
        if len(set(line)) < 3 and len(line) > 10:
            continue
        if any(line.lower().startswith(x) for x in ['from:', 'to:', 'subject:', 'date:', 'reply-to:']):
            continue
        cleaned_lines.append(line)

    cleaned_content = '\n'.join(cleaned_lines)
    # Increased content limit from 10000 to 20000
    if len(cleaned_content) > 20000:
        cleaned_content = cleaned_content[:20000] + '...'

    return cleaned_content

def extract_sender(msg_data):
    """Extract and clean sender."""
    headers = msg_data['payload'].get('headers', [])
    for header in headers:
        if header['name'].lower() == 'from':
            sender = header['value']
            if '<' in sender:
                sender = sender.split('<')[0].strip()
            return sender
    return "Unknown"

def extract_subject(msg_data):
    """Extract subject."""
    headers = msg_data['payload'].get('headers', [])
    for header in headers:
        if header['name'].lower() == 'subject':
            return header['value']
    return "No Subject"

def extract_date(msg_data):
    """Extract date."""
    headers = msg_data['payload'].get('headers', [])
    for header in headers:
        if header['name'].lower() == 'date':
            return header['value']
    return ""

def repair_json(json_str):
    """Attempt to repair common JSON issues using json-repair library."""
    try:
        # Use the json-repair library for robust repair
        repaired = json_repair_lib(json_str)
        if isinstance(repaired, str):
            return repaired
        # If it returns a dict, convert back to string
        return json.dumps(repaired)
    except Exception as e:
        print(f"  json-repair failed: {e}")
        # Fallback to basic cleanup
        json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
        return json_str

def summarize_with_gemini(newsletters, retry_count=0):
    """Summarize newsletters using Gemini."""
    max_retries = 2

    if not newsletters:
        return {
            'executive_summary': ["No newsletters found in last 24 hours."],
            'featured_analysis': [],
            'themes': [],
            'interest_insights': {},
            'fallback': False
        }

    if retry_count == 0:
        print(f"\nSummarizing {len(newsletters)} newsletters with Gemini...")
    else:
        print(f"\nRetrying Gemini summarization (attempt {retry_count + 1})...")

    # Prepare input for Gemini
    newsletter_data = []
    for i, nl in enumerate(newsletters, 1):
        newsletter_data.append(f"""
Newsletter {i}:
From: {nl['sender']}
Subject: {nl['subject']}
Content: {nl['content'][:3000]}
---
""")

    prompt = f"""You are an executive assistant preparing a daily briefing about markets, tech, and AI.

READER BRAND PILLARS (content strategy focus areas):
- Vibe coding / AI-augmented development
- AI agent orchestration and infrastructure
- Data-driven investing (equities, options, crypto)
- Tech strategy and market analysis
- Building in public / content creation

Prioritize themes that align with these content pillars. When a newsletter topic connects to one of these areas, note the connection explicitly.

Prioritize the explicitly configured newsletter senders: {", ".join(PRIORITY_NEWSLETTERS) or "none configured"}

Here are {len(newsletters)} newsletters from the last 24 hours:

{''.join(newsletter_data)}

TASK: Analyze these newsletters and provide:

1. **Executive Summary** - 3-5 bullet points of the most important insights (concise, punchy).

2. **Featured Analysis** (PRIORITY ONLY) - For each priority newsletter found, provide:
   - Detailed 3-4 sentence summary of key insights
   - Notable data points or charts mentioned (describe what the chart shows)
   - Content creation potential: "HIGH/MEDIUM/LOW" with brief reason
   - Source and subject

3. **Theme Analysis** - Group remaining newsletters into 3-4 key themes (AI, markets, crypto, tech, etc.).

4. **For each theme:**
   - 2-3 bullet points with concise 1-2 sentence summaries
   - Sources listed for each bullet
   - A "so_what" field explaining the implications/takeaways for an investor/content creator

Format your response as structured JSON:
{{
  "executive_summary": ["bullet 1", "bullet 2", "bullet 3"],
  "featured_analysis": [
    {{
      "source": "Newsletter Name",
      "subject": "...",
      "summary": "3-4 sentence detailed summary...",
      "charts_mentioned": ["description of chart 1", "description of chart 2"],
      "content_creation_potential": "HIGH - reason",
      "key_data_points": ["stat 1", "stat 2"],
      "so_what": "Why this matters - implications for investors/creators"
    }}
  ],
  "themes": [
    {{
      "name": "Theme Name",
      "topics": [
        {{
          "summary": "1-2 sentence summary...",
          "sources": ["Sender1", "Sender2"]
        }}
      ],
      "so_what": "The key takeaway - what should the reader pay attention to or act on?"
    }}
  ],
  "interest_insights": {{
    "core_interests": ["topic1", "topic2"],
    "companies_mentioned": ["company1", "company2"],
    "trusted_sources": ["source1", "source2"],
    "emerging_interests": ["new topic"],
    "content_opportunities": ["topic 1 from priority sources - good for YouTube/blog"],
    "reader_profile": "1-2 sentence insight about what this reveals about the reader's focus and priorities"
  }}
}}

IMPORTANT:
- ALWAYS include featured_analysis for any priority newsletters found
- Priority newsletters get 3-4 sentence summaries, others get 1-2 sentences
- Note any charts or data visualizations mentioned (describe them)
- Tag content creation potential for priority sources
- Extract interest insights: what topics/companies the reader consistently follows
- Identify trusted newsletter sources (quality over quantity)
- Note any emerging interests (new topics appearing)
- When a theme connects to the reader’s brand pillars (vibe coding, AI agents, data-driven investing, tech strategy, building in public), note the connection explicitly
- Return ONLY valid JSON, no other text"""

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=8192,
                response_mime_type='application/json',
            )
        )

        content = response.text
        print("✓ Gemini summarization complete")

        # Parse JSON response
        # Remove markdown code blocks if present
        content_cleaned = content.strip()
        if content_cleaned.startswith('```'):
            # Remove opening ```json or ```
            content_cleaned = re.sub(r'^```(?:json)?\s*', '', content_cleaned)
            # Remove closing ```
            content_cleaned = re.sub(r'\s*```$', '', content_cleaned)

        # Extract JSON from response
        json_match = re.search(r'\{[\s\S]*\}', content_cleaned)
        if json_match:
            summary_text = json_match.group()
        else:
            print(f"⚠ No JSON found. Response preview: {content[:200]}...")
            summary_text = content_cleaned

        summary = json.loads(summary_text)

        print(f"✓ Generated {len(summary.get('themes', []))} themes")
        print(f"✓ Featured {len(summary.get('featured_analysis', []))} priority newsletters")

        # Handle executive_summary as array or string
        exec_summary = summary.get('executive_summary', [])
        if isinstance(exec_summary, str):
            exec_summary = [exec_summary]

        # Validate theme structure
        validated_themes = []
        for theme in summary.get('themes', []):
            if not isinstance(theme, dict):
                print(f"  ⚠ Skipping invalid theme (not a dict): {theme}")
                continue
            if not isinstance(theme.get('name'), str) or not theme['name'].strip():
                print(f"  ⚠ Skipping theme with missing/invalid name: {theme}")
                continue
            if not isinstance(theme.get('topics'), list):
                print(f"  ⚠ Theme '{theme.get('name')}' has no topics list, using empty list")
                theme['topics'] = []
            else:
                # Validate each topic has required fields
                valid_topics = []
                for topic in theme['topics']:
                    if isinstance(topic, dict) and isinstance(topic.get('summary'), str) and isinstance(topic.get('sources'), list):
                        valid_topics.append(topic)
                    else:
                        print(f"  ⚠ Skipping invalid topic in theme '{theme['name']}': {topic}")
                theme['topics'] = valid_topics
            validated_themes.append(theme)

        if len(validated_themes) < len(summary.get('themes', [])):
            print(f"  ⚠ Validated {len(validated_themes)}/{len(summary.get('themes', []))} themes after structure check")

        return {
            'executive_summary': exec_summary,
            'featured_analysis': summary.get('featured_analysis', []),
            'themes': validated_themes,
            'interest_insights': summary.get('interest_insights', {}),
            'fallback': False
        }

    except json.JSONDecodeError as e:
        print(f"⚠ JSON parse error: {e}")

        # Try to repair JSON
        print("  Attempting JSON repair...")
        try:
            repaired = repair_json(summary_text)
            summary = json.loads(repaired)
            print("✓ JSON repaired successfully!")

            # Ensure we have required fields
            if 'themes' not in summary:
                summary['themes'] = []
            if 'executive_summary' not in summary:
                summary['executive_summary'] = ["Summary generated with repairs - some content may be truncated."]

            return {
                'executive_summary': summary.get('executive_summary', []),
                'featured_analysis': summary.get('featured_analysis', []),
                'themes': summary.get('themes', []),
                'interest_insights': summary.get('interest_insights', {}),
                'fallback': False
            }
        except Exception as repair_error:
            print(f"  Repair failed: {repair_error}")

            # Retry if we haven't exhausted retries
            if retry_count < max_retries:
                print(f"  Retrying with fresh Gemini call...")
                return summarize_with_gemini(newsletters, retry_count + 1)
            else:
                print("❌ Max retries exhausted.")
                return {
                    'executive_summary': [],
                    'featured_analysis': [],
                    'themes': [],
                    'interest_insights': {},
                    'fallback': True
                }

    except Exception as e:
        print(f"❌ Error calling Gemini API: {e}")
        if 'content' in dir():
            print(f"⚠ Response preview: {content[:500] if content else 'EMPTY'}...")

        # Retry if we haven't exhausted retries
        if retry_count < max_retries:
            print(f"  Retrying ({retry_count + 1}/{max_retries})...")
            return summarize_with_gemini(newsletters, retry_count + 1)
        else:
            print("❌ Max retries exhausted.")
            return {
                'executive_summary': [],
                'featured_analysis': [],
                'themes': [],
                'interest_insights': {},
                'fallback': True
            }

def enrich_themes_for_replies(summary, newsletters):
    """Enrich newsletter themes with X-searchable queries and author X handles.
    
    For each theme, generates 2-4 short keyword queries optimized for X search.
    Also collects X handles of newsletter authors who wrote about each theme,
    so the reply pipeline can search their timelines directly.
    """
    if not summary.get('themes'):
        return summary

    # Known newsletter author -> X handle mapping
    KNOWN_X_HANDLES = {
        'tomtunguz': '@ttunguz',
        'stratechery': '@benthompson',
        'cloudedjudgement': '@jasonlk',
        'bilello': '@charliebilello',
        'a16z': '@aaborowitz',
        'ben-evans': '@benedictevans',
        'therundownai': '@therundownai',
        'alphasignal': '@AlphaSignalAI',
        'mckinsey': '@McKinsey',
        'bain': '@BainInsights',
        'ben Thompson': '@benthompson',
        'tom tunguz': '@ttunguz',
        'charlie bilello': '@charliebilello',
        'benedict evans': '@benedictevans',
    }

    # Collect sender emails and names from newsletters
    newsletter_authors = {}
    for nl in newsletters:
        sender_email = nl.get('sender_email', '').lower()
        sender_name = nl.get('sender', '').lower()
        # Try to find X handle from known mapping
        x_handle = None
        for key, handle in KNOWN_X_HANDLES.items():
            if key in sender_email or key in sender_name:
                x_handle = handle
                break
        newsletter_authors[sender_email] = {
            'name': nl.get('sender', ''),
            'email': sender_email,
            'x_handle': x_handle,
        }

    # Keyword extraction patterns for X search queries
    TOPIC_QUERY_PATTERNS = {
        'ai agent': ['AI agents', 'AI agent tools', 'building AI agents'],
        'enterprise': ['AI agents enterprise', 'enterprise AI'],
        'scaling': ['scaling AI', 'AI infrastructure'],
        'regulation': ['tech regulation', 'AI regulation'],
        'social media': ['social media regulation', 'social media law'],
        'market': ['AI investing', 'stock market AI'],
        'prediction': ['prediction markets', 'AI trading'],
        'vibe coding': ['vibe coding', 'AI coding tools', 'prompt engineering'],
        'infrastructure': ['AI infrastructure', 'AI middleware'],
        'investing': ['AI investing', 'quant trading'],
        'build in public': ['build in public', 'indie hacker'],
        'content creation': ['content creation AI', 'AI creator tools'],
        'open source': ['open source AI', 'AI open source'],
        'model': ['LLM models', 'AI models', 'foundation models'],
        'safety': ['AI safety', 'AI alignment'],
        'startup': ['AI startups', 'startup funding'],
        'productivity': ['AI productivity', 'developer tools'],
        'automation': ['AI automation', 'workflow automation'],
    }

    for theme in summary['themes']:
        name = theme.get('name', '').lower()
        
        # Generate search queries from theme name
        queries = []
        for key, patterns in TOPIC_QUERY_PATTERNS.items():
            if key in name:
                queries.extend(patterns)
                break
        else:
            # Generic: use first 2-3 significant words
            words = [w for w in name.split() if len(w) > 3 and w.lower() not in ('the', 'and', 'for', 'with', 'that', 'this')]
            if len(words) >= 2:
                queries.append(' '.join(words[:3]))
        
        # Deduplicate and limit
        seen = set()
        unique_queries = []
        for q in queries:
            q_lower = q.lower().strip()
            if q_lower and q_lower not in seen and len(q) <= 30:
                seen.add(q_lower)
                unique_queries.append(q)
        theme['search_queries'] = unique_queries[:4]

        # Find newsletter authors who contributed to this theme
        theme_sources = []
        for topic in theme.get('topics', []):
            for src in topic.get('sources', []):
                theme_sources.append(src.lower())
        
        theme_x_handles = []
        for email, author_info in newsletter_authors.items():
            if author_info['x_handle']:
                # Check if this author is a source for this theme
                author_name = author_info['name'].lower()
                for src in theme_sources:
                    if src in author_name or author_name in src or src in email:
                        theme_x_handles.append(author_info['x_handle'])
                        break
        
        theme['author_x_handles'] = list(set(theme_x_handles))
        
        # Priority rank based on content_creation_potential and source quality
        rank = 5  # default
        has_priority_source = any(
            src.lower() in ['tom tunguz', 'stratechery', 'ben thompson', 'clouded judgement', 
                           'charlie bilello', 'a16z', 'benedict evans']
            for src in theme_sources
        )
        if has_priority_source:
            rank = 3  # higher priority (lower = better)
        if theme.get('so_what') and len(theme['so_what']) > 50:
            rank = min(rank, 2)  # strong so_what = even higher
        if theme_x_handles:
            rank = min(rank, 1)  # has author handles = highest
        theme['priority_rank'] = rank

    # Sort themes by priority rank
    summary['themes'].sort(key=lambda t: t.get('priority_rank', 5))

    print(f"  ✓ Enriched {len(summary['themes'])} themes with search queries")
    themes_with_authors = sum(1 for t in summary['themes'] if t.get('author_x_handles'))
    print(f"  ✓ {themes_with_authors} themes have newsletter author X handles")
    for t in summary['themes']:
        handles_str = ', '.join(t.get('author_x_handles', [])) or 'none'
        print(f"    [{t.get('priority_rank', '?')}] {t['name']} | queries: {t.get('search_queries', [])} | authors: {handles_str}")

    return summary


def save_summary_to_wiki_market(summary, newsletters):
    """Save newsletter summary to wiki-market daily feeds, not Hermes memory."""
    wiki_feeds_dir = (os.environ.get('NEWSLETTER_WIKI_FEEDS_DIR') or configured_text('${ANALYST_WIKI_ROOT}/daily/feeds'))
    os.makedirs(wiki_feeds_dir, exist_ok=True)

    date_str = datetime.now().strftime('%Y-%m-%d')
    wiki_file = os.path.join(wiki_feeds_dir, f'newsletters_{date_str}.md')

    with open(wiki_file, 'w') as f:
        f.write(f"# Newsletter Feed - {date_str}\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("Source: Gmail newsletters label via `newsletter_summarizer.py`\n\n")
        f.write("> Newsletter summaries are source/research artifacts. They belong in wiki-market/cron outputs, not Hermes global memory.\n\n")
        f.write("---\n\n")

        # Executive summary as bullets
        f.write("## Executive Summary\n\n")
        exec_summary = summary.get('executive_summary', [])
        if isinstance(exec_summary, list):
            for bullet in exec_summary:
                f.write(f"- {bullet}\n")
        else:
            f.write(f"{exec_summary}\n")
        f.write("\n")

        # Featured analysis
        if summary.get('featured_analysis'):
            f.write("## Featured Sources\n\n")
            for item in summary['featured_analysis']:
                f.write(f"### {item.get('source', 'Unknown')}: {item.get('subject', '')}\n\n")
                f.write(f"- Summary: {item.get('summary', '')[:300]}...\n")
                if item.get('so_what'):
                    f.write(f"- So What: {item['so_what']}\n")
                f.write("\n")

        f.write("## Themes Identified\n\n")
        for theme in summary.get('themes', []):
            rank = theme.get('priority_rank', '?')
            queries = theme.get('search_queries', [])
            handles = theme.get('author_x_handles', [])
            f.write(f"### {theme['name']} (priority: {rank})\n\n")
            if queries:
                f.write(f"- Search queries: {', '.join(queries)}\n")
            if handles:
                f.write(f"- Author X handles: {', '.join(handles)}\n")
            for topic in theme.get('topics', []):
                f.write(f"- {topic['summary'][:250]}...\n")
                f.write(f"  - Sources: {', '.join(topic['sources'])}\n")
            if theme.get('so_what'):
                f.write(f"- 💡 So What: {theme['so_what']}\n")
            f.write("\n")

        f.write("## Sources\n\n")
        for newsletter in newsletters:
            f.write(f"- {newsletter['sender']}: {newsletter['subject'][:80]}...\n")
        f.write("\n")

    print(f"✓ Summary saved to wiki-market feed {wiki_file}")
    return wiki_file


def append_interest_insights_to_wiki_market(interest_insights, wiki_file=None):
    """Append reader interest/content insights to the wiki-market newsletter feed."""
    if not wiki_file:
        wiki_feeds_dir = (os.environ.get('NEWSLETTER_WIKI_FEEDS_DIR') or configured_text('${ANALYST_WIKI_ROOT}/daily/feeds'))
        os.makedirs(wiki_feeds_dir, exist_ok=True)
        wiki_file = os.path.join(
            wiki_feeds_dir,
            f"newsletters_{datetime.now().strftime('%Y-%m-%d')}.md",
        )

    with open(wiki_file, 'a') as f:
        f.write("## Reader Interest / Content Signals\n\n")

        if interest_insights.get('reader_profile'):
            f.write(f"**Reader Profile:** {interest_insights['reader_profile']}\n\n")

        if interest_insights.get('core_interests'):
            f.write("**Core Interests:**\n")
            for interest in interest_insights['core_interests'][:5]:
                f.write(f"- {interest}\n")
            f.write("\n")

        if interest_insights.get('companies_mentioned'):
            f.write("**Companies/Projects Mentioned:**\n")
            for company in interest_insights['companies_mentioned'][:5]:
                f.write(f"- {company}\n")
            f.write("\n")

        if interest_insights.get('trusted_sources'):
            f.write("**Trusted Sources (from today's newsletters):**\n")
            for source in interest_insights['trusted_sources'][:5]:
                f.write(f"- {source}\n")
            f.write("\n")

        if interest_insights.get('emerging_interests'):
            f.write("**Emerging Interests:**\n")
            for interest in interest_insights['emerging_interests'][:3]:
                f.write(f"- {interest}\n")
            f.write("\n")

        if interest_insights.get('content_opportunities'):
            f.write("**X Content Opportunities:**\n")
            for opportunity in interest_insights['content_opportunities'][:5]:
                f.write(f"- {opportunity}\n")
            f.write("\n")

    print(f"✓ Interest insights appended to wiki-market feed {wiki_file}")

def save_briefing_to_file(summary, newsletters):
    """Save newsletter briefing to file for V's X content topics."""
    # Create briefing directory
    briefing_dir = os.path.expanduser(configured_text('${ANALYST_HERMES_HOME}/content_calendar/briefings'))
    os.makedirs(briefing_dir, exist_ok=True)

    # Filename with date
    date_str = datetime.now().strftime('%Y-%m-%d')
    briefing_file = f'{briefing_dir}/briefing_{date_str}.md'

    with open(briefing_file, 'w') as f:
        f.write(f'# Newsletter Briefing - {date_str}\n\n')
        f.write(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n\n')
        f.write(f'\n---\n\n')

        # Featured analysis (best for X content)
        if summary.get('featured_analysis'):
            f.write('## Featured Content\n\n')
            for item in summary['featured_analysis'][:5]:
                source = item.get('source', 'Unknown')
                insight = item.get('insight', '')
                f.write(f'### {source}\n')
                f.write(f'{insight}\n\n')

        # Themes
        if summary.get('themes'):
            f.write('## Major Themes\n\n')
            for theme in summary['themes']:
                f.write(f'### {theme["name"]}\n')
                for topic in theme.get('topics', []):
                    f.write(f'- {topic["summary"]}\n')
                    f.write(f'  Sources: {", ".join(topic["sources"])}\n')
                if theme.get('so_what'):
                    f.write(f'💡 So What: {theme["so_what"]}\n')
                f.write('\n')

        # Content opportunities (direct X tweet ideas)
        if summary.get('interest_insights', {}).get('content_opportunities'):
            f.write('## X Content Opportunities\n\n')
            f.write('Ready-to-use tweet ideas from today\'s newsletters:\n\n')
            for i, opportunity in enumerate(summary['interest_insights']['content_opportunities'][:10], 1):
                f.write(f'{i}. {opportunity}\n')
            f.write('\n')

        # Newsletter sources
        if newsletters:
            f.write('## Sources\n\n')
            for nl in newsletters:
                sender = nl.get('sender', 'Unknown')
                f.write(f'- {sender}\n')
            f.write('\n')

    print(f"✓ Briefing saved to {briefing_file}")
    return briefing_file

def main():
    """Main execution."""
    print("="*80)
    print("NEWSLETTER BRIEFING - GEMINI 3 FLASH PREVIEW")
    print("="*80)

    # Authenticate
    print("\nAuthenticating with Gmail...")
    service = authenticate_gmail()
    if not service:
        print("❌ Failed to authenticate with Gmail")
        return False
    print("✓ Connected to Gmail")

    # Fetch newsletters
    print("\nFetching newsletters (last 24 hours)...")
    newsletters = get_newsletters(service, hours_back=24)
    print(f"✓ Found {len(newsletters)} newsletters")

    if not newsletters:
        print("\n⚠ No newsletters found in last 24 hours.")
        return False

    # Summarize with Gemini
    print("\nAnalyzing and summarizing with Gemini...")
    summary = summarize_with_gemini(newsletters)

    # If fallback was used
    if summary.get('fallback', False):
        print("\n⚠ AI summarization used fallback mode.")

    print(f"✓ Generated {len(summary['themes'])} themes")

    # Save briefing to file
    print("\nSaving briefing to file for V's X content...")
    briefing_file = save_briefing_to_file(summary, newsletters)

    # Enrich themes with X-ready search queries and newsletter author X handles
    print("\nEnriching themes with search queries and author X handles...")
    summary = enrich_themes_for_replies(summary, newsletters)

    # Save to wiki-market (newsletter artifacts do not belong in Hermes memory)
    wiki_file = save_summary_to_wiki_market(summary, newsletters)

    # Save interest insights into the same wiki-market feed
    if summary.get('interest_insights'):
        append_interest_insights_to_wiki_market(summary['interest_insights'], wiki_file)

    print("\n" + "="*80)
    print("✓ DAILY BRIEFING SAVED")
    print("="*80)

    return True

if __name__ == '__main__':
    import sys
    success = main()
    sys.exit(0 if success else 1)
