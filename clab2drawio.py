from cli.parser_clab2drawio import parse_arguments
from core.diagram.custom_drawio import CustomDrawioDiagram
from core.grafana.grafana_manager import GrafanaDashboard
from core.utils.yaml_processor import YAMLProcessor
from core.data.topology_loader import TopologyLoader, TopologyLoaderError
from core.data.node_link_builder import NodeLinkBuilder
from core.data.graph_level_manager import GraphLevelManager
from core.layout.vertical_layout import VerticalLayout
from core.layout.horizontal_layout import HorizontalLayout
from core.config.theme_manager import ThemeManager, ThemeManagerError
from core.interactivity.interactive_manager import InteractiveManager
from core.diagram.diagram_builder import DiagramBuilder
from core.logging_config import configure_logging
import os
import sys
import logging

logger = logging.getLogger(__name__)


def main(
    input_file: str,
    output_file: str,
    grafana: bool,
    theme: str,
    include_unlinked_nodes: bool = False,
    no_links: bool = False,
    layout: str = "vertical",
    verbose: bool = False,
    interactive: bool = False,
    grafana_config_path: str = None,
) -> None:
    """
    Main function to generate a topology diagram from a containerlab YAML or draw.io XML file.

    :param input_file: Path to the containerlab YAML file.
    :param output_file: Output file path for the generated diagram.
    :param grafana: Whether to generate Grafana dashboard artifacts.
    :param theme: Theme name or path to a custom theme file.
    :param include_unlinked_nodes: Include nodes without any links in the topology diagram.
    :param no_links: Do not draw links between nodes.
    :param layout: Layout direction ("vertical" or "horizontal").
    :param verbose: Enable verbose output.
    :param interactive: Run in interactive mode to define graph-levels and icons.
    """
    logger.debug("Starting clab2drawio main function.")
    loader = TopologyLoader()
    try:
        containerlab_data = loader.load(input_file)
    except TopologyLoaderError:
        logger.error("Failed to load topology. Exiting.")
        sys.exit(1)

    try:
        if os.path.isabs(theme):
            theme_path = theme
        else:
            theme_path = os.path.join(script_dir, "styles", f"{theme}.yaml")

        if not os.path.exists(theme_path):
            raise FileNotFoundError(
                f"The specified theme file '{theme_path}' does not exist."
            )
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.error(f"An error occurred while loading the theme: {e}")
        sys.exit(1)

    # Use ThemeManager to load styles
    logger.debug("Loading theme...")
    theme_manager = ThemeManager(theme_path)

    try:
        styles = theme_manager.load_theme()
    except ThemeManagerError:
        logger.error("Failed to load theme. Exiting.")
        sys.exit(1)
    logger.debug("Theme loaded successfully, building diagram...")

    diagram = CustomDrawioDiagram()
    diagram.layout = layout
    diagram.styles = styles

    # Determine the prefix
    prefix = containerlab_data.get("prefix", "clab")
    lab_name = containerlab_data.get("name", "")

    # Use NodeLinkBuilder to build nodes and links
    logger.debug("Building nodes and links...")
    builder = NodeLinkBuilder(containerlab_data, styles, prefix, lab_name)
    nodes, links = builder.build_nodes_and_links()

    diagram.nodes = nodes

    if not include_unlinked_nodes:
        connected_nodes = {name: node for name, node in nodes.items() if node.links}
        diagram.nodes = connected_nodes
        nodes = diagram.nodes
    else:
        diagram.nodes = nodes

    available_themes = theme_manager.list_available_themes()
    available_themes.sort()

    if interactive:
        logger.debug("Entering interactive mode...")
        processor = YAMLProcessor()
        interactor = InteractiveManager()
        interactor.run_interactive_mode(
            diagram=diagram,
            available_themes=available_themes,
            icon_to_group_mapping=styles["icon_to_group_mapping"],
            containerlab_data=containerlab_data,
            output_file=input_file,
            processor=processor,
            prefix=prefix,
            lab_name=lab_name,
        )
        # After wizard finishes:
        layout = interactor.final_summary.get("Layout", layout)
        chosen_theme = interactor.final_summary.get("Theme")

        if chosen_theme:
            # Load that theme or switch to it
            new_theme_path = os.path.join(
                os.path.dirname(theme_path), f"{chosen_theme}.yaml"
            )
            if os.path.exists(new_theme_path):
                logger.debug(f"Loading user-chosen theme: {chosen_theme}")
                theme_manager.config_path = new_theme_path
                styles = theme_manager.load_theme()
            else:
                logger.warning(
                    f"User chose theme '{chosen_theme}' but no file found. Keeping old theme."
                )

    # Check if any nodes have predefined positions from the YAML
    has_predefined_positions = any(
        node.pos_x is not None
        and node.pos_y is not None
        and str(node.pos_x).strip() != ""
        and str(node.pos_y).strip() != ""
        for node in nodes.values()
    )

    if has_predefined_positions:
        logger.debug("Using predefined positions from YAML file with scaling...")

        # Scale factor to ensure adequate spacing between nodes
        x_scale = (styles.get("padding_x", 150) / 100) * 1.5
        y_scale = (styles.get("padding_y", 150) / 100) * 1.5

        # Convert string positions to float and apply scaling
        for node in nodes.values():
            try:
                if (
                    node.pos_x is not None
                    and node.pos_y is not None
                    and str(node.pos_x).strip() != ""
                    and str(node.pos_y).strip() != ""
                ):
                    node.pos_x = int(node.pos_x) * x_scale
                    node.pos_y = int(node.pos_y) * y_scale
            except (ValueError, TypeError):
                logger.debug(
                    f"Could not convert position for node {node.name}, will use layout position"
                )
                node.pos_x = None
                node.pos_y = None

        # When fixed positions are available, we still assign graph levels for connectivity purposes
        # but instruct it to skip warnings and not override positions
        logger.debug(
            "Using predefined positions - graph levels will only be used for connectivity"
        )
        graph_manager = GraphLevelManager()
        graph_manager.assign_graphlevels(
            diagram, verbose=False, skip_warnings=True, respect_fixed_positions=True
        )
    else:
        # No fixed positions, proceed with normal graph level assignment
        logger.debug("No predefined positions found - assigning graph levels normally")
        graph_manager = GraphLevelManager()
        graph_manager.assign_graphlevels(diagram, verbose=False)

    # Only apply layout manager if we don't have predefined positions
    if not has_predefined_positions:
        # Choose layout based on layout argument
        if layout == "vertical":
            layout_manager = VerticalLayout()
        else:
            layout_manager = HorizontalLayout()

        logger.debug(f"Applying {layout} layout...")
        layout_manager.apply(diagram, verbose=verbose)

    # Calculate the diagram size based on the positions of the nodes
    min_x = min(node.pos_x for node in nodes.values())
    min_y = min(node.pos_y for node in nodes.values())
    max_x = max(node.pos_x for node in nodes.values())
    max_y = max(node.pos_y for node in nodes.values())

    # Determine the necessary adjustments
    adjust_x = -min_x + 100  # Adjust so the minimum x is at least 100
    adjust_y = -min_y + 100  # Adjust so the minimum y is at least 100

    # Apply adjustments to each node's position
    for node in nodes.values():
        node.pos_x += adjust_x
        node.pos_y += adjust_y

    # Recalculate diagram size if necessary, after adjustment
    max_x = max(node.pos_x for node in nodes.values())
    max_y = max(node.pos_y for node in nodes.values())

    max_size_x = max_x + 100  # Adding a margin to the right side
    max_size_y = max_y + 100  # Adding a margin to the bottom

    if styles["pagew"] == "auto":
        styles["pagew"] = max_size_x
    if styles["pageh"] == "auto":
        styles["pageh"] = max_size_y

    logger.debug("Updating diagram style...")
    diagram.update_style(styles)

    diagram.add_diagram("Network Topology")

    diagram_builder = DiagramBuilder()
    logger.debug("Adding nodes to diagram...")
    diagram_builder.add_nodes(diagram, diagram.nodes, styles)

    if grafana:
        styles["ports"] = True

    if styles["ports"]:
        logger.debug("Adding ports and generating Grafana dashboard...")
        diagram_builder.add_ports(diagram, styles)
        if not output_file:
            grafana_output_file = os.path.splitext(input_file)[0] + ".grafana.json"
        output_folder = os.path.dirname(grafana_output_file) or "."
        diagram.grafana_dashboard_file = grafana_output_file
        os.makedirs(output_folder, exist_ok=True)

        grafana_dashboard = GrafanaDashboard(
            diagram, grafana_config_path=grafana_config_path
        )
        panel_config = grafana_dashboard.create_panel_yaml()

        flow_panel_output_file = (
            os.path.splitext(grafana_output_file)[0] + ".flow_panel.yaml"
        )
        with open(flow_panel_output_file, "w") as f:
            f.write(panel_config)
        print("Saved flow panel YAML to:", flow_panel_output_file)

        grafana_json = grafana_dashboard.create_dashboard(panel_config)
        with open(grafana_output_file, "w") as f:
            f.write(grafana_json)
        print("Saved Grafana dashboard JSON to:", grafana_output_file)
    else:
        logger.debug("Adding links to diagram...")
        diagram_builder.add_links(diagram, styles)

    if not output_file:
        output_file = os.path.splitext(input_file)[0] + ".drawio"

    output_folder = os.path.dirname(output_file) or "."
    output_filename = os.path.basename(output_file)
    os.makedirs(output_folder, exist_ok=True)

    logger.debug(f"Dumping diagram to file: {output_file}")
    diagram.dump_file(filename=output_filename, folder=output_folder)

    print("Saved file to:", output_file)


if __name__ == "__main__":
    args = parse_arguments()

    script_dir = os.path.dirname(__file__)

    # Configure logging at startup
    log_level = logging.DEBUG if args.verbose else logging.INFO
    configure_logging(level=log_level)

    main(
        input_file=args.input,
        output_file=args.output,
        grafana=args.gf_dashboard,
        theme=args.theme,
        include_unlinked_nodes=args.include_unlinked_nodes,
        no_links=args.no_links,
        layout=args.layout,
        verbose=args.verbose,
        interactive=args.interactive,
        grafana_config_path=args.grafana_config,
    )
