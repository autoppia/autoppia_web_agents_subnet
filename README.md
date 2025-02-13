<div align="center">

# **Web Agents Subnet (Bittensor Sn36)**
### [🌐 Autoppia Website](https://autoppia.com/infinite-web-arena-subnet)  
### [⛏️ Mining Docs](https://github.com/autoppia/autoppia_web_agents_subnet-deprecated-/blob/main/docs/miner.md)&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;[🧑‍🏫 Validating Docs](docs/validator.md)&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;[🔗 IWA](https://github.com/autoppia/autoppia_iwa)
### [💬 Discord](https://autoppia.com/infinite-web-arena-subnet)  
</div>


---

## 🔍 Overview
**Web Agents Subnet** leverages our **Infinite Web Arena (IWA)** benchmark to incentivize **Bittensor Miners** to develop powerful **Web Agents**. 

Current state-of-the-art benchmarks for web operation are quite limited and can be easily gamed by memorization and training on the dataset. **IWA** solves these limitations by using **generative AI** and **synthetic data** to create a continuous stream of **novel and dynamic web challenges**. This approach ensures agents face realistic tasks that demand ongoing adaptation, reasoning, and generalization.

Our goal is to make **IWA** the default benchmark for web agents and establish **Subnet 36 web agents** as the world's best web operators. By rewarding miners who develop high-performing agents, **IWA** ensures scalability, continuous improvement, and robust evaluations without static datasets or human bottlenecks.

## 🌐 IWA Benchmark
IWA is a scalable & dynamic benchmark designed to evaluate autonomous web agents in environments that mirror the infinite complexity of the real web.

### 1. Web Environment Generation Module
We use a combination of **metaprogramming**, **Gen AI**, and other techniques to auto generate diverse demo websites that:
* Mirror real web complexity while enabling unrestricted agent operations through sophisticated generation techniques that preserve authenticity while removing real-world constraints
* Bypass real-website constraints like payments, authentication and other non-desired outcomes through careful environment design and controlled simulation
* Remain dynamic to prevent memorization by continuously generating new variations of test environments and scenarios

### 2. Web Analysis Module
* We crawl and analyze entire domains to create comprehensive knowledge files that capture a website's structure, content, and functionality
* These analyses help build a high-level understanding of complete website functionality and structure
* Having general domain knowledge proves essential when operating on specific URLs, allowing agents to understand broader context and patterns

### 3. Task Generation
We generate tasks synthetically for given web environments by:
* Orchestrating LLMs, knowledge files and dynamic web content to automatically create realistic web tasks
* Generating diverse scenarios reflecting real-world situations
* Incorporating random data (e.g., random products in an ecommerce site) to enhance realism
* Leveraging use cases characterized by low variety in type but high in possible combinations. 

> **Note:** Websites are designed around a limited number of core task types, but each task can occur in countless variations due to diverse details and combinations possible. For example, purchasing can involve various product choices, prices, or order details.

### 4. Test Generation
We employ various executable tests to determine task completion:
* **HTML Verification**: Checks for specific strings and DOM structure
* **Backend Event Testing**: Validates server-side interactions (demo websites only)
* **Visual Assessment**: Uses vision models to verify task completion via screenshots
* **LLM-based Evaluation**: Analyzes DOM/HTML to assess task success
* **Hybrid Testing**: Combines multiple verification methods for robust evaluation

### 5. Web Agents
The core of IWA and what we evaluate:
* Autonomous systems navigating and interacting with web environments through sophisticated decision-making
* Complete assigned tasks through strategic action sequences, demonstrating adaptability and effectiveness

### 6. Evaluation
The evaluation process involves:
* Launching a fresh browser instance via the validator.
* Executing the sequence of actions provided by the miner.
* Capturing snapshots after each action to document progress.
* Running task-associated tests on the captured snapshots.
* Generating a final score based on the outcomes of the tests.


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
3. **Task Solution**: Miners use their web agents to solve tasks and return sequences of *Actions*
4. **Evaluation Process**:
   - Validator launches fresh browser instance
   - Executes the sequence of actions returned by miner
   - Takes snapshots after each action
   - Runs task-associated tests on snapshots
   - Generates final score based on test results

## 🚀 **Argonaut** - A Permissionless Web Operator Powered by Bittensor

**Argonaut** is a **fully permissionless web operator**, leveraging **Bittensor’s Subnet 36** and **Autonomous Web Agents** to transform business automation. Instead of rigid, pre-built software solutions, Argonaut provides a **customizable and adaptive** automation layer that evolves with **specific business needs**.

Unlike traditional **SaaS, ERP, and CRM** systems, Argonaut operates in an **open and decentralized** manner—allowing businesses to define **highly tailored automation workflows** while benefiting from a **competitive network of miners** improving automation intelligence in real-time.

## 🌐 How Argonaut Works
Argonaut is **not a single AI agent**—it's an **ecosystem** of **autonomous web agents** developed by **Bittensor miners** on **Subnet 36**. These agents are rigorously tested and optimized through our **Infinite Web Arena (IWA)** benchmark, ensuring businesses always have access to the most advanced web automation capabilities.

### What Makes Argonaut Unique?
Instead of relying on **pre-programmed scripts** or **static AI models**, Argonaut enables **businesses to define their own automation requirements** while leveraging a **competitive, decentralized network** to execute and refine them.

- **Customizable Solutions** – Tailor automation to **specific business operations**, instead of relying on generic SaaS tools.
- **Scalability** – Leverage a **growing network of decentralized miners** to improve performance over time.
- **Adaptability** – Agents dynamically adjust to new workflows, **handling real-world web environments**.
- **Permissionless Deployment** – Open participation, **no vendor lock-in**, and **continuous improvements from miner competition**.

## 🔄 The Future of Business Operations with Argonaut

Argonaut goal is revolutionizing how every industry leverages web-based software by automating the low-value, routine tasks that bog down operations. In a world where businesses rely on the web for nearly all functions, the ability to automate web operations becomes essential for efficiency and growth.

### Universal Web-Based Automation
- **Cross-industry innovation**: All sectors—from finance to retail—can harness automation to streamline routine web tasks.
- **Customizable workflows**: Tailor automated processes to fit unique business needs without the burden of costly integrations.
- **Operational agility**: Reduce dependency on complex, traditional software by transitioning to dynamic web operations.

### Enhancing Business Efficiency
- **Focus on high-impact work**: Automate low-value tasks, freeing up human talent for strategic initiatives.
- **Cost-effective integration**: Seamlessly incorporate automated processes into existing web infrastructures.
- **Smart data management**: Leverage AI-driven capabilities for document processing and data synchronization, enhancing decision-making and operational consistency.

With Argonaut, the future of business operations is defined by the power of web automation—transforming everyday workflows into efficient, scalable, and intelligent processes.


## 📜 License
*Built with ❤️ by the Autoppia Team*