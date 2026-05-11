"""Training hub article content data.

Each article has:
- slug: URL-friendly identifier
- title: Display title
- description: Short description for cards/meta
- icon: Emoji icon for the card
- category: Machine category key
- category_label: Human-readable category
- read_time: Minutes to read
- published_date: ISO date string
- tags: List of search tags
- content_html: Full HTML body content

For MVP, articles 0-2 have full content; others have placeholders
ready for AI agent generation.
"""

ARTICLES = [
    {
        "slug": "get-deepseek-api-key",
        "title": "How to Get Your DeepSeek API Key in 2 Minutes",
        "description": "A fast step-by-step guide to creating your DeepSeek account and generating an API key for your AI agents.",
        "icon": "🔑",
        "category": "api-setup",
        "category_label": "API Setup",
        "read_time": 3,
        "published_date": "2026-05-10",
        "tags": ["api key", "deepseek", "setup", "configuration"],
        "content_html": """
<h2>What You Need</h2>
<p>Before your AI agents can start working, they need an API key to connect to DeepSeek's language model. This takes about 2 minutes and requires only an email address.</p>

<div class="tip">
    <span class="tip-icon">💡</span>
    <p><strong>Tip:</strong> Your API key is like a password. Never share it publicly or commit it to GitHub.</p>
</div>

<h2>Step 1: Create a DeepSeek Account</h2>
<div class="step">
    <div class="step-num">1</div>
    <div class="step-content">
        <p>Go to <a href="https://platform.deepseek.com" target="_blank">platform.deepseek.com</a> and click <strong>Sign Up</strong>.</p>
        <p>Enter your email address and create a password. You can also sign up with Google or GitHub.</p>
    </div>
</div>

<div class="step">
    <div class="step-num">2</div>
    <div class="step-content">
        <p>Check your email for the verification link and click it to confirm your account.</p>
    </div>
</div>

<h2>Step 2: Generate Your API Key</h2>
<div class="step">
    <div class="step-num">3</div>
    <div class="step-content">
        <p>Log in to your DeepSeek account and navigate to the <strong>API Keys</strong> section in the left sidebar.</p>
    </div>
</div>

<div class="step">
    <div class="step-num">4</div>
    <div class="step-content">
        <p>Click <strong>Create API Key</strong>. Give it a name like <code>Laval Digital Agents</code> so you can identify it later.</p>
    </div>
</div>

<div class="step">
    <div class="step-num">5</div>
    <div class="step-content">
        <p>Copy the generated key immediately — it starts with <code>sk-</code>. You won't be able to see it again after you close the dialog.</p>
    </div>
</div>

<h2>Step 3: Add It to Your Dashboard</h2>
<div class="step">
    <div class="step-num">6</div>
    <div class="step-content">
        <p>Log in to your <a href="/client/login">Laval Digital client dashboard</a> and go to the <strong>Agent Configuration</strong> tab.</p>
    </div>
</div>

<div class="step">
    <div class="step-num">7</div>
    <div class="step-content">
        <p>Select any agent (e.g. "Local SEO"), paste your API key into the <strong>API Key</strong> field, and click <strong>Detect</strong> to verify it works.</p>
    </div>
</div>

<div class="step">
    <div class="step-num">8</div>
    <div class="step-content">
        <p>Click <strong>Save Configuration</strong>. Your agent is now ready to use!</p>
    </div>
</div>

<div class="tip">
    <span class="tip-icon">💡</span>
    <p><strong>Pro tip:</strong> You can use the same API key for all your agents. Use the "All Agents" option in the config dropdown to apply it everywhere at once.</p>
</div>

<div class="warning">
    <span class="warn-icon">⚠️</span>
    <p><strong>Important:</strong> DeepSeek offers free credits for new accounts. Check their pricing page to understand usage costs before running large campaigns.</p>
</div>
"""
    },
    {
        "slug": "point-domain-to-website",
        "title": "How to Point Your Domain to Your New Website",
        "description": "DNS setup instructions for Namecheap, GoDaddy, and Google Domains to connect your domain to your Laval Digital site.",
        "icon": "🌐",
        "category": "getting-started",
        "category_label": "Getting Started",
        "read_time": 5,
        "published_date": "2026-05-10",
        "tags": ["domain", "dns", "nameservers", "website", "setup"],
        "content_html": """
<h2>Overview</h2>
<p>After we deploy your website, you'll want to point your domain name (like <code>myplumbingbusiness.com</code>) to it. This is done through DNS settings at your domain registrar. Don't worry — it's a simple process that takes about 10 minutes.</p>

<h2>What You'll Need</h2>
<ul>
    <li>Your domain registrar login (where you bought the domain)</li>
    <li>The DNS target we provided in your welcome email (e.g., <code>client123.lavaldigital.ca</code>)</li>
</ul>

<h2>Option A: Namecheap</h2>
<div class="step">
    <div class="step-num">1</div>
    <div class="step-content">
        <p>Log in to your Namecheap account and go to <strong>Dashboard &gt; Domain List</strong>.</p>
    </div>
</div>
<div class="step">
    <div class="step-num">2</div>
    <div class="step-content">
        <p>Click <strong>Manage</strong> next to your domain, then select the <strong>Advanced DNS</strong> tab.</p>
    </div>
</div>
<div class="step">
    <div class="step-num">3</div>
    <div class="step-content">
        <p>Under <strong>Host Records</strong>, add a <strong>CNAME Record</strong>:</p>
        <ul>
            <li><strong>Type:</strong> CNAME</li>
            <li><strong>Host:</strong> @ or www</li>
            <li><strong>Target:</strong> <code>client123.lavaldigital.ca</code> (use the target from your email)</li>
            <li><strong>TTL:</strong> Automatic</li>
        </ul>
    </div>
</div>
<div class="step">
    <div class="step-num">4</div>
    <div class="step-content">
        <p>Click the green checkmark to save. DNS changes typically take 5-30 minutes to propagate.</p>
    </div>
</div>

<h2>Option B: GoDaddy</h2>
<div class="step">
    <div class="step-num">1</div>
    <div class="step-content">
        <p>Log in to your GoDaddy account and go to <strong>Products &gt; Domains</strong>.</p>
    </div>
</div>
<div class="step">
    <div class="step-num">2</div>
    <div class="step-content">
        <p>Click <strong>DNS</strong> next to your domain, then scroll to the <strong>Records</strong> section.</p>
    </div>
</div>
<div class="step">
    <div class="step-num">3</div>
    <div class="step-content">
        <p>Click <strong>Add Record</strong>, select <strong>CNAME</strong>, and enter:</p>
        <ul>
            <li><strong>Name:</strong> @</li>
            <li><strong>Value:</strong> <code>client123.lavaldigital.ca</code></li>
            <li><strong>TTL:</strong> 1 hour</li>
        </ul>
    </div>
</div>
<div class="step">
    <div class="step-num">4</div>
    <div class="step-content">
        <p>Click <strong>Save</strong>. GoDaddy may show a confirmation — just confirm the change.</p>
    </div>
</div>

<h2>Option C: Google Domains</h2>
<div class="step">
    <div class="step-num">1</div>
    <div class="step-content">
        <p>Go to <a href="https://domains.google.com" target="_blank">domains.google.com</a> and sign in.</p>
    </div>
</div>
<div class="step">
    <div class="step-num">2</div>
    <div class="step-content">
        <p>Click your domain name, then click <strong>DNS</strong> in the left sidebar.</p>
    </div>
</div>
<div class="step">
    <div class="step-num">3</div>
    <div class="step-content">
        <p>Scroll to <strong>Custom resource records</strong> and click <strong>Add new record</strong>:</p>
        <ul>
            <li><strong>Type:</strong> CNAME</li>
            <li><strong>Host name:</strong> @</li>
            <li><strong>Destination:</strong> <code>client123.lavaldigital.ca</code></li>
            <li><strong>TTL:</strong> 1h</li>
        </ul>
    </div>
</div>
<div class="step">
    <div class="step-num">4</div>
    <div class="step-content">
        <p>Click <strong>Save</strong>. Changes usually take effect within a few minutes.</p>
    </div>
</div>

<div class="tip">
    <span class="tip-icon">💡</span>
    <p><strong>Not sure?</strong> Email us at support@lavaldigital.ca and we'll help you configure your DNS. Managed services clients get this done for them automatically.</p>
</div>
"""
    },
    {
        "slug": "understand-agent-dashboard",
        "title": "Understanding Your AI Agent Dashboard",
        "description": "A complete walkthrough of every tab, button, and metric in your client dashboard.",
        "icon": "📊",
        "category": "getting-started",
        "category_label": "Getting Started",
        "read_time": 4,
        "published_date": "2026-05-10",
        "tags": ["dashboard", "navigation", "overview", "agents"],
        "content_html": """
<h2>Welcome to Your Dashboard</h2>
<p>Your Laval Digital client dashboard is the command center for your AI marketing suite. Here's a tour of everything you'll see.</p>

<h2>Top Navigation Bar</h2>
<p>The navigation bar at the top gives you quick access to all major sections:</p>
<ul>
    <li><strong>My Dashboard</strong> — The main overview page you're looking at now</li>
    <li><strong>Submit Task</strong> — Send a request to your AI agents</li>
    <li><strong>My Payments</strong> — View your installment plan and payment history</li>
    <li><strong>Analytics</strong> — See leads, tasks, and performance metrics</li>
    <li><strong>Managed Services</strong> — Upgrade to fully managed or check your status</li>
</ul>

<h2>Stats Cards</h2>
<p>At the top of the dashboard, four stat cards give you a snapshot of your account:</p>
<ul>
    <li><strong>Project Status</strong> — Shows "Live" once your website is deployed</li>
    <li><strong>AI Agents Active</strong> — How many of your 11 agents are currently enabled (e.g., 11/11)</li>
    <li><strong>Tasks This Month</strong> — Total completed tasks across all agents</li>
    <li><strong>Website</strong> — Your live site URL (once deployed)</li>
</ul>

<h2>Managed Services Card</h2>
<p>This card shows your current service level:</p>
<ul>
    <li><strong>Self-Service</strong> — You manage approvals yourself. Upgrade to managed anytime.</li>
    <li><strong>Fully Managed</strong> — Our team handles all approvals and publishing for you.</li>
</ul>

<h2>Payment Schedule</h2>
<p>Your installment plan is displayed here with each payment's amount, due date, and paid/unpaid status. You'll also see your total paid and remaining balance.</p>

<h2>Submit a Request</h2>
<p>This is where you tell your AI agents what to do. Type your request in plain English (e.g., <em>"I need more plumbing leads in Laval this week"</em>) and click Submit. The orchestrator routes your request to the right agent automatically.</p>

<h2>Download Contract</h2>
<p>Your signed agreement is available here for download.</p>

<h2>Analytics Tab</h2>
<p>Click the Analytics nav link to see detailed metrics:</p>
<ul>
    <li><strong>Leads This Month</strong> — Total leads captured</li>
    <li><strong>Tasks Run</strong> — Total agent executions</li>
    <li><strong>Agent Success Rate</strong> — Percentage of successful executions</li>
    <li><strong>Recent Leads & Executions</strong> — Tables showing your latest activity</li>
</ul>

<div class="tip">
    <span class="tip-icon">💡</span>
    <p><strong>Tip:</strong> Bookmark your dashboard URL so you can check in quickly every morning. Most self-service clients spend about 3 minutes per day reviewing and approving content.</p>
</div>
"""
    },
    {
        "slug": "approve-ai-content",
        "title": "How to Approve AI-Generated Content",
        "description": "The approval flow explained simply — how drafts are created, reviewed, and published by your AI agents.",
        "icon": "✅",
        "category": "getting-started",
        "category_label": "Getting Started",
        "read_time": 3,
        "published_date": "2026-05-10",
        "tags": ["approvals", "content", "review", "publishing"],
        "content_html": """
<h2>The AI Content Workflow</h2>
<p>When you submit a task or your agents work autonomously, here's the path every piece of content follows:</p>
<ol>
    <li><strong>Agent creates a draft</strong> — The AI writes content based on your request or its scheduled tasks</li>
    <li><strong>Draft awaits approval</strong> — It appears in your Pending Approvals section</li>
    <li><strong>You review</strong> — Read the draft, make sure it matches your brand voice</li>
    <li><strong>Approve or reject</strong> — One click approves it for publishing; reject with feedback for revision</li>
    <li><strong>Content is executed</strong> — Approved content gets published to your blog, social media, or ad platform</li>
</ol>
<p>If you're on a Managed Services plan, steps 3 and 4 are handled by our team.</p>
"""
    },
    {
        "slug": "seo-agent-daily-work",
        "title": "What Your AI SEO Agent Does Every Day",
        "description": "Behind the scenes of automated SEO: keyword research, content generation, Google Business Profile optimization, and more.",
        "icon": "🔍",
        "category": "seo",
        "category_label": "SEO",
        "read_time": 4,
        "published_date": "2026-05-10",
        "tags": ["seo", "local-seo", "google", "keywords"],
        "content_html": """
<h2>24/7 SEO Automation</h2>
<p>Your Local SEO agent works around the clock to improve your search rankings. Here's what it does every day:</p>
<ul>
    <li><strong>Keyword Research</strong> — Discovers high-value local keywords your competitors are ranking for</li>
    <li><strong>Service Page Creation</strong> — Generates optimized pages for each service you offer</li>
    <li><strong>Google Business Profile</strong> — Monitors and suggests GBP post content and updates</li>
    <li><strong>Local Citations</strong> — Identifies citation opportunities on local directories</li>
    <li><strong>Content Optimization</strong> — Refines existing pages with better keywords and structure</li>
</ul>
"""
    },
    {
        "slug": "read-monthly-analytics-report",
        "title": "How to Read Your Monthly Analytics Report",
        "description": "Understanding your ROI: leads, conversions, task success rates, and what the numbers mean for your business.",
        "icon": "📈",
        "category": "analytics",
        "category_label": "Analytics",
        "read_time": 3,
        "published_date": "2026-05-10",
        "tags": ["analytics", "report", "roi", "metrics"],
        "content_html": """
<h2>Your Monthly Performance Snapshot</h2>
<p>Each month, you'll receive a Performance Report that shows exactly how your AI agents are performing. Here's how to read it:</p>
<ul>
    <li><strong>Leads</strong> — Total new leads captured during the month. Higher is better.</li>
    <li><strong>Tasks</strong> — Total tasks executed. Growing month over month means your agents are getting more done.</li>
    <li><strong>Success Rate</strong> — Percentage of tasks that completed without errors. 90%+ is excellent.</li>
    <li><strong>Active Agents</strong> — How many of your 11 agents were active this month.</li>
</ul>
"""
    },
    {
        "slug": "get-facebook-access-token",
        "title": "Getting Your Facebook Page Access Token",
        "description": "Step-by-step guide to obtaining a Facebook access token for social media automation.",
        "icon": "📘",
        "category": "social-media",
        "category_label": "Social Media",
        "read_time": 4,
        "published_date": "2026-05-10",
        "tags": ["facebook", "access token", "social media", "api"],
        "content_html": """
<h2>Why You Need a Page Access Token</h2>
<p>Your Social Media agent needs a Facebook Page Access Token to post content, respond to comments, and analyze engagement on your Facebook page.</p>
<p>Full guide coming soon. In the meantime, contact support and we'll help you set it up.</p>
"""
    },
    {
        "slug": "add-manager-google-business",
        "title": "How to Add Us as a Manager on Your Google Business Profile",
        "description": "Screenshot guide to granting Laval Digital manager access to your Google Business Profile.",
        "icon": "📍",
        "category": "seo",
        "category_label": "SEO",
        "read_time": 3,
        "published_date": "2026-05-10",
        "tags": ["google business profile", "gbp", "manager", "access"],
        "content_html": """
<h2>Granting Access to Your GBP</h2>
<p>To optimize your Google Business Profile, we need manager access. Here's how to add us:</p>
<ol>
    <li>Go to <a href="https://business.google.com" target="_blank">business.google.com</a> and sign in</li>
    <li>Click the three dots menu on your profile, then <strong>Business Profile settings</strong></li>
    <li>Click <strong>People and access</strong> in the left menu</li>
    <li>Click <strong>Add</strong>, enter <code>support@lavaldigital.ca</code>, and select <strong>Manager</strong> role</li>
    <li>Click <strong>Invite</strong> and let us know you've sent the invitation</li>
</ol>
"""
    },
    {
        "slug": "3-minute-daily-checklist",
        "title": "The 3-Minute Daily Dashboard Checklist",
        "description": "A quick daily routine for self-service clients to keep everything running smoothly.",
        "icon": "✅",
        "category": "getting-started",
        "category_label": "Getting Started",
        "read_time": 2,
        "published_date": "2026-05-10",
        "tags": ["daily", "checklist", "routine", "self-service"],
        "content_html": """
<h2>Your Daily 3-Minute Routine</h2>
<p>Spend just 3 minutes each morning to keep your AI marketing on track:</p>
<ol>
    <li><strong>Check for pending approvals</strong> — Review and approve any AI drafts waiting for you</li>
    <li><strong>View your stats</strong> — Glance at your leads and tasks counts</li>
    <li><strong>Submit one request</strong> — If you have a new promotion or need content, send it to your agents</li>
</ol>
"""
    },
    {
        "slug": "how-ai-agents-work-together",
        "title": "How Our AI Agents Work Together",
        "description": "The architecture explained in plain language — how 11 specialized agents coordinate to market your business.",
        "icon": "🤖",
        "category": "getting-started",
        "category_label": "Getting Started",
        "read_time": 5,
        "published_date": "2026-05-10",
        "tags": ["architecture", "agents", "orchestrator", "how-it-works"],
        "content_html": """
<h2>The AI Team Behind Your Business</h2>
<p>Think of your 11 AI agents as a specialized marketing team. Each has a specific role, and they all work together under the direction of the Orchestrator.</p>
<ul>
    <li><strong>Local SEO Agent</strong> — Handles Google rankings and local search visibility</li>
    <li><strong>Social Media Agent</strong> — Creates and schedules posts across platforms</li>
    <li><strong>Lead Conversion Agent</strong> — Follows up with leads and nurtures them</li>
    <li><strong>Paid Ads Agent</strong> — Manages Google and Meta ad campaigns</li>
    <li><strong>Growth Hacker</strong> — Finds creative growth opportunities</li>
    <li><strong>Plus 6 more specialists</strong> — Email, TikTok, Outreach, Backlinks, Reputation, and Executioner</li>
</ul>
"""
    },
]
