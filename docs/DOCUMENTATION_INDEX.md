# MuJoCo MCP Documentation Index

## 📚 Complete Documentation Guide

Welcome to the MuJoCo MCP documentation. This index provides a comprehensive overview of all available documentation and guides you to the right resources.

### Current Version: **v0.8.2**
### MCP Protocol: **2024-11-05 Standard**
### Last Updated: June 2025

---

## 🚀 Getting Started

### For New Users
1. **[README.md](README.md)** - Project overview and quick start
2. **[Installation Guide](#installation)** - Detailed setup instructions
3. **[Examples](examples/)** - Demo applications and tutorials

### For Developers
1. **[Architecture Overview](#architecture)** - System design and components
2. **[API Reference](#api-reference)** - Complete API documentation
3. **[CONTRIBUTING.md](CONTRIBUTING.md)** - How to contribute

---

## 📖 Core Documentation

### System Overview
- **[README.md](../README.md)**
  - Project introduction
  - Quick start guide
  - Basic features
  - Example usage

### Architecture & Design
- **[CLAUDE.md](../CLAUDE.md)**
  - AI-specific guidance
  - Architecture details
  - Development workflow
  - Design philosophy

### Feature Documentation
- **[SCENES_DOCUMENTATION.md](SCENES_DOCUMENTATION.md)**
  - Built-in physics scenes
  - Scene parameters
  - Custom scene creation

- **[ADVANCED_FEATURES_GUIDE.md](ADVANCED_FEATURES_GUIDE.md)**
  - Advanced control algorithms
  - Multi-robot coordination
  - Sensor feedback systems
  - RL integration
  - Visualization tools

### Motion Control
- **[README_MOTION_CONTROL.md](../examples/README_MOTION_CONTROL.md)**
  - Motion control demos
  - MuJoCo Menagerie integration
  - Robot configurations
  - Control strategies

---

## 🔧 Technical Reference

### API Documentation
- **MCP Tools** (9 total)
  - `get_server_info` - Server status and capabilities
  - `create_scene` - Create physics simulation
  - `step_simulation` - Advance simulation time
  - `get_state` - Current simulation data
  - `set_joint_positions` - Control joint angles
  - `reset_simulation` - Reset to initial state
  - `execute_command` - Natural language control
  - `get_loaded_models` - List active simulations
  - `close_viewer` - Close MuJoCo GUI window

### Change History
- **[CHANGELOG.md](../CHANGELOG.md)**
  - Version history
  - Feature additions
  - Bug fixes
  - Breaking changes

### Testing & Quality
- **[TESTING_SUMMARY.md](../reports/TESTING_SUMMARY.md)**
  - Test coverage
  - Known issues
  - Performance metrics
  - Production readiness

---

## 🛠️ Development Resources

### Contributor Guides
- **[AGENTS.md](AGENTS.md)** - Repository guidelines and workflow expectations

### Installation & Setup

#### Basic Setup
```bash
# Clone repository
git clone https://github.com/agent-next/mujoco-agent.git
cd mujoco-agent

# Install in development mode
pip install -e .

# Configure Claude Desktop
cp configs/cursor_mcp_config.json ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

#### Advanced Setup
```bash
# Install MuJoCo Menagerie (for robot models)
git clone https://github.com/google-deepmind/mujoco_menagerie.git ~/mujoco_menagerie

# Start enhanced viewer server
/opt/miniconda3/bin/mjpython mujoco_viewer_server_enhanced.py

# Run benchmarks
python benchmarks/physics_benchmarks.py

# Test advanced features
python test_advanced_features.py
```

### Architecture Overview

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ Claude Desktop  │────▶│   MCP Server    │────▶│ Viewer Server   │
│  (MCP Client)   │◀────│  (Python SDK)   │◀────│   (MuJoCo)      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        JSON-RPC          Socket (8888)           launch_passive()
```

### Module Structure
```
mujoco-mcp/
├── src/mujoco_mcp/
│   ├── __init__.py              # Package initialization
│   ├── __main__.py              # Entry point
│   ├── server.py                # Main MCP server
│   ├── viewer_client.py         # Socket client
│   ├── mcp_server.py            # MCP protocol handler
│   ├── advanced_controllers.py  # Control algorithms
│   ├── multi_robot_coordinator.py # Multi-robot systems
│   ├── sensor_feedback.py       # Sensor processing
│   ├── rl_integration.py        # RL environments
│   └── visualization_tools.py   # Real-time plotting
├── examples/
│   ├── motion_control_demo.py   # Direct control demo
│   └── mcp_motion_control.py    # MCP interface demo
├── benchmarks/
│   └── physics_benchmarks.py    # Performance tests
└── mujoco_viewer_server.py      # Viewer server
```

---

## 📋 Common Tasks

### Creating a Simple Simulation
```python
# In Claude Desktop
"Create a pendulum simulation"
"Set the pendulum angle to 45 degrees"
"Step the simulation 100 times"
```

### Loading Robot Models
```python
# Load from MuJoCo Menagerie
"Load Franka Panda robot"
"Create a Unitree Go2 scene"
"Show me the Shadow Hand model"
```

### Advanced Control
```python
# Using Python API
from mujoco_mcp.advanced_controllers import create_arm_controller

controller = create_arm_controller("franka_panda")
controller.set_trajectory(waypoints, times)
```

### Multi-Robot Coordination
```python
from mujoco_mcp.multi_robot_coordinator import MultiRobotCoordinator

coordinator = MultiRobotCoordinator()
coordinator.add_robot("arm1", "franka_panda", {"manipulation": True})
coordinator.add_robot("arm2", "ur5e", {"manipulation": True})
coordinator.start_coordination()
```

---

## 🐛 Troubleshooting

### Common Issues

1. **"Failed to connect to MuJoCo viewer server"**
   - Ensure `mujoco_viewer_server.py` is running
   - Check if port 8888 is available
   - Use `/opt/miniconda3/bin/mjpython` on macOS

2. **"MuJoCo Menagerie not found"**
   - Install: `git clone https://github.com/google-deepmind/mujoco_menagerie.git`
   - Set: `export MUJOCO_MENAGERIE_PATH=~/mujoco_menagerie`

3. **"Model not found"**
   - Verify model exists in Menagerie installation
   - Check robot_configs in motion_control_demo.py

4. **Performance Issues**
   - Use enhanced viewer server for production
   - Enable connection pooling
   - Monitor with built-in diagnostics

### Getting Help
- Check [TESTING_SUMMARY.md](TESTING_SUMMARY.md) for known issues
- Review examples in [examples/](examples/) directory
- Consult [ADVANCED_FEATURES_GUIDE.md](ADVANCED_FEATURES_GUIDE.md) for complex use cases

---

## 📚 Additional Resources

### External Documentation
- [MCP Specification](https://modelcontextprotocol.io/specification/2024-11-05)
- [MuJoCo Documentation](https://mujoco.readthedocs.io/)
- [MuJoCo Menagerie](https://github.com/google-deepmind/mujoco_menagerie)
- [Gymnasium Documentation](https://gymnasium.farama.org/)

### Related Projects
- [Blender MCP](https://github.com/ahujasid/blender-mcp) - Similar architecture
- [MuJoCo MPC](https://github.com/google-deepmind/mujoco_mpc) - Model predictive control
- [dm_control](https://github.com/google-deepmind/dm_control) - DeepMind control suite

### Community
- Report issues: [GitHub Issues](https://github.com/agent-next/mujoco-agent/issues)
- Discussions: Use GitHub Discussions for questions
- Contributing: See [CONTRIBUTING.md](CONTRIBUTING.md)

---

## 📈 Project Status

- **Version**: 0.8.2
- **Status**: Production Ready
- **Test Coverage**: 4/6 advanced features passing
- **Documentation**: Comprehensive (this index)
- **License**: MIT

Last documentation update: June 2025
