<div align="center" style="width: 100%;">
  <picture style="width: 100%;">
    <source srcset="autoppia_logo_black_font.png" media="(prefers-color-scheme: dark)" style="width: 100%;">
    <source srcset="autoppia_logo_black_font.png" media="(prefers-color-scheme: light)" style="width: 100%;">
    <img src="autoppia_logo_black_font.png" alt="Autoppia Logo" style="width: 100%; max-width: 100%;">
  </picture>
</div>

## 🔍 Overview

**Web Agents Subnet** leverages our **Infinite Web Arena (IWA)** benchmark to incentivize **Bittensor Miners** to develop powerful **Web Agents**.

Current state-of-the-art benchmarks for web operation are quite limited and can be easily gamed by memorization and training on the dataset. **IWA** solves these limitations by using **generative AI** and **synthetic data** to create a continuous stream of **novel and dynamic web challenges**. This approach ensures agents face realistic tasks that demand ongoing adaptation, reasoning, and generalization.

Our goal is to make **IWA** the default benchmark for web agents and establish **Subnet 36 web agents** as the world's best web operators. By rewarding miners who develop high-performing agents, **IWA** ensures scalability, continuous improvement, and robust evaluations without static datasets or human bottlenecks.

## 🌐 IWA Benchmark

IWA is a scalable & dynamic benchmark designed to evaluate autonomous web agents in environments that mirror the infinite complexity of the real web.

### 1. Web Environment Generation Module

We use a combination of **metaprogramming**, **Gen AI**, and other techniques to auto generate diverse demo websites that:

- Mirror real web complexity while enabling unrestricted agent operations through sophisticated generation techniques that preserve authenticity while removing real-world constraints
- Bypass real-website constraints like payments, authentication and other non-desired outcomes through careful environment design and controlled simulation
- Remain dynamic to prevent memorization by continuously generating new variations of test environments and scenarios

### 2. Web Analysis Module

- We crawl and analyze entire domains to create comprehensive knowledge files that capture a website's structure, content, and functionality
- These analyses help build a high-level understanding of complete website functionality and structure
- Having general domain knowledge proves essential when operating on specific URLs, allowing agents to understand broader context and patterns

### 3. Task Generation

We generate tasks synthetically for given web environments by:

- Orchestrating LLMs, knowledge files and dynamic web content to automatically create realistic web tasks
- Generating diverse scenarios reflecting real-world situations
- Incorporating random data (e.g., random products in an ecommerce site) to enhance realism
- Leveraging use cases characterized by low variety in type but high in possible combinations.

> **Note:** Websites are designed around a limited number of core task types, but each task can occur in countless variations due to diverse details and combinations possible. For example, purchasing can involve various product choices, prices, or order details.

### 4. Test Generation

We employ various executable tests to determine task completion:

- **HTML Verification**: Checks for specific strings and DOM structure
- **Backend Event Testing**: Validates server-side interactions (demo websites only)
- **Visual Assessment**: Uses vision models to verify task completion via screenshots
- **LLM-based Evaluation**: Analyzes DOM/HTML to assess task success
- **Hybrid Testing**: Combines multiple verification methods for robust evaluation

### 5. Web Agents

The core of IWA and what we evaluate:

- Autonomous systems navigating and interacting with web environments through sophisticated decision-making
- Complete assigned tasks through strategic action sequences, demonstrating adaptability and effectiveness

### 6. Evaluation

The evaluation process involves:

- Launching a fresh browser instance via the validator.
- Executing the sequence of actions provided by the miner.
- Capturing snapshots after each action to document progress.
- Running task-associated tests on the captured snapshots.
- Generating a final score based on the outcomes of the tests.

## ⚙️ Subnet Mechanics

### 🧑‍🏫 Validator Role

Validators are responsible for:

- Generating diverse web tasks using **IWA**
- Distributing tasks to miners
- Executing and verifying solutions
- Assigning weights on the **Bittensor Blockchain**

### ⛏️ Miner Role

Miners contribute by:

- Developing state-of-the-art **Web Agents**
- Processing incoming tasks
- Generating precise action sequences
- Continuously improving agent performance

### 🎯 Incentive Mechanism

We want to reward miners for their **performance and speed**. It's essential that Web Agents complete **arbitrarily complex workflows** in minimal time to drive real adoption and skyrocket productivity. **Reliable and fast Web Operation** is key. If validation is done correctly miners will consistently deliver exceptional results!

#### Task Distribution & Evaluation

1. **Task Generation**: Validators create diverse web tasks via IWA
2. **Distribution**: Tasks sent to miners in randomized batches
3. **Task Solution**: Miners use their web agents to solve tasks and return sequences of _Actions_
4. **Evaluation Process**:
   - Validator launches fresh browser instance
   - Executes the sequence of actions returned by miner
   - Takes snapshots after each action
   - Runs task-associated tests on snapshots
   - Generates final score based on test results

## 🚀 **Autoppia Web Operator** - A Permissionless Web Operator Powered by Bittensor

**Autoppia Web Operator** is a **fully permissionless web operator**, leveraging **Bittensor’s Subnet 36** and **Autonomous Web Agents** to transform business automation. Instead of rigid, pre-built software solutions, this tool provides a **customizable and adaptive** automation layer that evolves with **specific business needs**.

Traditional **RPA tools** are like robots following a strict cookbook - they can only follow pre-written recipes and fail when ingredients change. If a button moves or a website updates, **everything breaks**. For each task, you need to painfully program:

1. Every single step in the process
2. Every possible error scenario
3. Every alternative path
4. Every edge case that might occur

Autoppia Web Operator revolutionizes this with **intelligent web agents** that work like skilled chefs - they **understand the goal** and can **improvise**. Need to fill out a form? Book a flight? Process an order? Just tell them what you need, and they'll:

- **Navigate Dynamically** - Find their way even when interfaces change
- **Handle Surprises** - Deal with unexpected popups or new elements
- **Make Smart Decisions** - Choose the best path based on context
- **Complete Tasks** - Without needing step-by-step instructions

## 🌐 How it Works

Behind Autoppia is a **network of autonomous web agents** powered by **Bittensor's Subnet 36**. The difference is dramatic:

**Traditional Automation:**

- "Click exactly this button at coordinates (x,y)"
- "If error X appears, do Y"
- "Only proceed if condition Z is met"
- _Breaks when anything changes_

**Our Intelligent Agents:**

- "Book a flight to New York"
- "Process these invoices"
- "Update customer records"
- _Adapts to changes automatically_

What makes this truly **revolutionary**:

- **True Intelligence** – Agents understand context and adapt like humans do
- **Zero Programming** – No need to specify every possible scenario
- **Universal Automation** – If a human can do it in a browser, our agents can automate it
- **Self-Improving** – Agents get smarter through constant competition and learning

The result? **Effortless automation** that works with any website, adapts to changes, and keeps getting better over time.

## 🔄 The Future of Business

Our goal is revolutionizing how every industry leverages web-based software by automating the low-value, routine tasks that bog down operations. In a world where businesses rely on the web for nearly all functions, the ability to automate web operations becomes essential for efficiency and growth.

### Universal Web-Based Automation

- **Cross-industry innovation**: All sectors—from finance to retail—can harness automation to streamline routine web tasks.
- **Customizable workflows**: Tailor automated processes to fit unique business needs without the burden of costly integrations.
- **Operational agility**: Reduce dependency on complex, traditional software by transitioning to dynamic web operations.

### Enhancing Business Efficiency

- **Focus on high-impact work**: Automate low-value tasks, freeing up human talent for strategic initiatives.
- **Cost-effective integration**: Seamlessly incorporate automated processes into existing web infrastructures.
- **Smart data management**: Leverage AI-driven capabilities for document processing and data synchronization, enhancing decision-making and operational consistency.

With Autoppia Web Operator, the future of business operations is defined by the power of web automation—transforming everyday workflows into efficient, scalable, and intelligent processes.

## 📜 License

_Built with ❤️ by the Autoppia Team_
